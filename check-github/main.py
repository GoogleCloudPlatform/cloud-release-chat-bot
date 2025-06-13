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

# Assume github_rss_urls.py contains a list like:
# rss_urls = [
#     "https://github.com/GoogleCloudPlatform/terraformer/releases.atom",
#     "https://github.com/GoogleCloudPlatform/cloud-code-vscode/releases.atom",
#     # ... other repository URLs
# ]
from github_rss_urls import rss_urls

# --- Client Initializations ---
# It's a good practice to initialize clients outside of the function entry point
# to take advantage of connection reuse.

# Initialize Firestore Client
# The client will automatically use the project set in the environment.
firestore_client = firestore.Client()

# Initialize Pub/Sub Publisher Client with batch settings for efficiency
batch_settings = pubsub_v1.types.BatchSettings(
    max_messages=100,      # Max number of messages to batch.
    max_bytes=1024 * 10,   # Max size of batch in bytes.
    max_latency=1,         # Max seconds to wait before publishing.
)
publisher = pubsub_v1.PublisherClient(batch_settings)

# Construct the topic path from environment variables
project_id = os.environ.get("GCP_PROJECT_ID")
topic_name = os.environ.get("PUB_SUB_TOPIC_NAME")
if not project_id or not topic_name:
    raise ValueError("GCP_PROJECT_ID and PUB_SUB_TOPIC_NAME environment variables must be set.")
topic_path = publisher.topic_path(project_id, topic_name)

# List to hold all the futures for asynchronous publishing.
publish_futures = []


# --- Pub/Sub Callback ---
def callback(future: pubsub_v1.publisher.futures.Future) -> None:
    """Callback function to handle the result of a Pub/Sub publish operation."""
    try:
        message_id = future.result()
        print(f"Published message with ID: {message_id}")
    except Exception as e:
        print(f"Failed to publish message: {e}")


# --- Core Functions ---
def get_releases_from_rss(rss_url):
    """Parses a GitHub releases Atom feed and returns a map of recent releases."""
    release_map = {}
    try:
        page = requests.get(rss_url)
        page.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        soup = BeautifulSoup(page.content, "xml")

        # Extract the repository name from the feed's main title
        repo_name = soup.find("title").text.replace("Release notes from ", "")

        releases = soup.find_all("entry")
        today_date = datetime.now(timezone("US/Eastern")).date()

        for release in releases:
            updated_str = release.find("updated").text
            # datetime.fromisoformat correctly handles the 'Z' (UTC) timezone
            pub_date = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            
            # Compare dates in the same timezone
            if pub_date.astimezone(timezone("US/Eastern")).date() == today_date:
                release_id = release.find("id").text
                release_map[release_id] = {
                    "repo_name": repo_name,
                    "title": release.find("title").text,
                    "link": release.find("link")["href"],
                    "date": pub_date.strftime("%B %d, %Y"),
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


def store_new_releases(new_releases):
    """Stores the new releases in Firestore to prevent reprocessing."""
    if not new_releases:
        return

    doc_ref = firestore_client.collection("cloud_release_github").document("releases")
    
    # Format data for Firestore's update method. We use the release_id as the
    # key in the document's map field.
    update_data = {
        release_id: details for release_id, details in new_releases.items()
    }
    
    # Use update() to add new fields to the document without overwriting it.
    # If the document doesn't exist, it will be created.
    doc_ref.set(update_data, merge=True)
    print(f"Successfully stored {len(new_releases)} new releases in Firestore.")


def publish_to_pubsub(space_id, release):
    """Publishes a message to Pub/Sub with space ID and release details."""
    message_json = json.dumps({
        "space_id": space_id,
        "release": release,
    }).encode("utf-8")
    
    future = publisher.publish(topic_path, message_json)
    future.add_done_callback(callback)
    publish_futures.append(future)


def send_new_release_notifications():
    """Main function to check for and send new release notifications."""
    all_releases_map = {}
    with futures.ThreadPoolExecutor() as executor:
        # Concurrently fetch and parse all RSS feeds
        results = executor.map(get_releases_from_rss, rss_urls)
        for release_map in results:
            all_releases_map.update(release_map)

    new_releases_map = get_new_releases(all_releases_map)

    if not new_releases_map:
        print("No new releases found.")
        return

    subscriptions_ref = firestore_client.collection("github_repo_subscriptions")
    for release_id, release in new_releases_map.items():
        print(f"New release found: {release['repo_name']} {release['title']}")

        # Check for subscriptions based on repository name
        repo_doc = subscriptions_ref.document(release["repo_name"]).get()
        if repo_doc.exists:
            spaces_subscribed = repo_doc.to_dict().get("spaces_subscribed", [])
            for space in spaces_subscribed:
                publish_to_pubsub(space, release)
                print(f"Published notification for {release['repo_name']} to space {space}")

    store_new_releases(new_releases_map)

    # Wait for all the asynchronous publish calls to complete.
    futures.wait(publish_futures, return_when=futures.ALL_COMPLETED)
    print("All publish futures completed.")


# --- Cloud Function Entry Point ---
@functions_framework.http
def http_request(request):
    """
    HTTP-triggered Cloud Function entry point.
    """
    try:
        send_new_release_notifications()
        return ("Processing complete.", 200)
    except Exception as e:
        print(f"An error occurred during execution: {e}")
        return ("An internal error occurred.", 500)