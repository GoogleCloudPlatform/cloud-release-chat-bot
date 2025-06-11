# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
from concurrent import futures
from datetime import datetime

import functions_framework
import requests
from bs4 import BeautifulSoup
from google.cloud import firestore, pubsub_v1
from pytz import timezone
from github_rss_urls import rss_urls

# Removed genai client initialization

firestore_client = firestore.Client(project=os.environ.get("GCP_PROJECT_ID"))
batch_settings = pubsub_v1.types.BatchSettings(
    max_messages=100,
    max_bytes=1024,
    max_latency=1,
)
publisher = pubsub_v1.PublisherClient(batch_settings)
topic_path = publisher.topic_path(
    os.environ.get("GCP_PROJECT_ID"), os.environ.get("PUB_SUB_TOPIC_NAME")
)
publish_futures = []


# Resolve the publish future in a separate thread.
def callback(future: pubsub_v1.publisher.futures.Future) -> None:
    message_id = future.result()
    print(message_id)

def get_releases_from_rss(rss_url):
    """Parses a GitHub releases Atom feed and returns a map of recent releases."""
    release_map = {}
    try:
        page = requests.get(rss_url)
        page.raise_for_status()
        soup = BeautifulSoup(page.content, "xml")

        # Extract the repository name from the feed's main title
        repo_name = soup.find("title").text.replace("Release notes from ", "")

        releases = soup.find_all("entry")
        for release in releases:
            updated_str = release.find("updated").text
            # datetime.fromisoformat handles the timezone offset correctly
            pub_date = (
                datetime.fromisoformat(updated_str)
                .astimezone(timezone("US/Eastern"))
                .date()
            )
            today_date = datetime.now(timezone("US/Eastern")).date()

            if pub_date == today_date:
                release_id = release.find("id").text
                release_map[release_id] = {
                    "repo_name": repo_name,
                    "title": release.find("title").text,
                    "link": release.find("link")["href"],
                    "date": pub_date.strftime("%B %d, %Y"),
                    # The 'content' field is no longer needed without summarization
                }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching RSS feed {rss_url}: {e}")
    except Exception as e:
        print(f"Error parsing RSS feed {rss_url}: {e}")
    return release_map


def get_stored_releases():
    """Retrieves the map of already processed releases from Firestore."""
    doc_ref = firestore_client.collection("cloud_release_github").document("releases")
    doc = doc_ref.get()
    return doc.to_dict() if doc.exists else {}


def get_new_releases(release_map=None):
    """Compares fetched releases with stored ones to find what's new."""
    if release_map is None:
        return {}
    stored_release_map = get_stored_releases()
    new_releases_map = {
        release_id: details
        for release_id, details in release_map.items()
        if release_id not in stored_release_map
    }
    return new_releases_map


def publish_to_pubsub(space_id, release):
    """Publishes a message to Pub/Sub with space ID and release details."""
    message_json = json.dumps(
        {
            "space_id": space_id,
            "release": release,
        }
    ).encode("utf-8")
    future = publisher.publish(topic_path, message_json)
    future.add_done_callback(callback)
    publish_futures.append(future)
    print(f"Published message for release: {release['repo_name']} {release['title']}")


def send_new_release_notifications():
    """Main function to check for and send new release notifications."""
    all_releases_map = {}
    with futures.ThreadPoolExecutor() as executor:
        results = executor.map(get_releases_from_rss, rss_urls)
        for release_map in results:
            all_releases_map.update(release_map)

    new_releases_map = get_new_releases(all_releases_map)

    # Removed the block that called the summarization logic

    subscriptions_ref = firestore_client.collection("github_repo_subscriptions")
    for release_id, release in new_releases_map.items():
        print(f"New release found: {release['repo_name']} {release['title']}")

        # Check for subscriptions based on repository name
        repo_doc = subscriptions_ref.document(release["repo_name"]).get()
        if repo_doc.exists:
            spaces_subscribed = repo_doc.to_dict().get("spaces_subscribed", [])

@functions_framework.http
def http_request(request):
    """HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """
    send_new_release_notifications()
    return ("Done", 200)
