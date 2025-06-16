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
import re
from concurrent import futures
from datetime import datetime

import functions_framework
import requests
from bs4 import BeautifulSoup
from github_rss_urls import rss_urls
from google import genai
from google.cloud import firestore, pubsub_v1
from pytz import timezone

client = genai.Client(
    vertexai=True,
    location="us-central1",
)

firestore_client = firestore.Client(project=os.environ.get("GCP_PROJECT_ID"))
batch_settings = pubsub_v1.types.BatchSettings(
    max_messages=100,  # default 100 m
    max_bytes=1024,  # default 1 MB
    max_latency=1,  # default 10 ms
)
publisher = pubsub_v1.PublisherClient(batch_settings)
topic_path = publisher.topic_path(
    os.environ.get("GCP_PROJECT_ID"), os.environ.get("PUB_SUB_TOPIC_NAME")
)
publish_futures = []


# --- Pub/Sub Callback ---
def callback(future: pubsub_v1.publisher.futures.Future) -> None:
    """Handles the result of a Pub/Sub publish operation."""
    try:
        message_id = future.result()
        print(f"Published message with ID: {message_id}")
    except Exception as e:
        print(f"Failed to publish message: {e}")


# --- AI Summarization Function ---
def summarize_release_notes(content_html: str, release_title: str) -> str:
    """
    Generates a Google Chat-formatted summary of release notes using Vertex AI Gemini,
    inspired by the blog summarization template.
    """
    if not content_html:
        return "No content available for summary."

    soup = BeautifulSoup(content_html, "html.parser")
    text_content = soup.get_text(separator="\n", strip=True)
    text_content = re.sub(r"\n{3,}", "\n\n", text_content).strip()

    if not text_content or len(text_content) < 20:
        return "Summary not available."

    try:
        # This detailed prompt is adapted from the user-provided blog summarization example.
        prompt = f"""
        You are a helpful assistant that creates concise, easy-to-read summaries of GitHub release notes for developers.

        **Instructions:**
        1.  Your summary should be formatted for the Google Chat API.
        2.  *Do not* include the release title (e.g., "{release_title}") in your summary.
        3.  Focus on the most important changes: new features, major bug fixes, and any breaking changes.
        4.  Use bulleted lists for key changes. Each list item *must* start with an asterisk followed by a single space (e.g., `* New feature added.`).
        5.  Use bolding with asterisks (e.g., `*Breaking Changes*`) to highlight important sections or keywords.
        6.  Keep the summary brief and to the point. Avoid introductory phrases like "This release contains...".
        7.  *Do not* use nested bullet points or other complex formatting.

        **Here are the release notes to summarize:**
        ---
        {text_content}
        """

        response = client.models.generate_content(
            # https://ai.google.dev/gemini-api/docs/models
            model="gemini-2.5-pro-preview-05-06",
            contents=prompt,
        )

        if response.text:
            return response.text.strip()
        else:
            print(f"Gemini returned an empty response for release: {release_title}")
            return "AI summary could not be generated."

    except Exception as e:
        print(f"Error during summarization for release {release_title}: {e}")
        return "AI summary could not be generated."


# --- Core Functions ---
def get_releases_from_rss(rss_url):
    """Parses a GitHub releases Atom feed and returns a map of recent releases."""
    release_map = {}
    try:
        page = requests.get(rss_url)
        page.raise_for_status()
        soup = BeautifulSoup(page.content, "xml")

        repo_name = soup.find("title").text.replace("Release notes from ", "")
        releases = soup.find_all("entry")
        today_date = datetime.now(timezone("US/Eastern")).date()

        for release in releases:
            updated_str = release.find("updated").text
            pub_date = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))

            if pub_date.astimezone(timezone("US/Eastern")).date() == today_date:
                release_id = release.find("id").text
                release_map[release_id] = {
                    "repo_name": repo_name,
                    "title": release.find("title").text,
                    "link": release.find("link")["href"],
                    "date": pub_date.strftime("%B %d, %Y"),
                    "content": release.find("content").text,
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
    return {
        release_id: details
        for release_id, details in release_map.items()
        if release_id not in stored_release_map
    }


def store_new_releases(new_releases):
    """Stores the new releases in Firestore to prevent reprocessing."""
    if not new_releases:
        return

    doc_ref = firestore_client.collection("cloud_release_github").document("releases")
    update_data = {release_id: details for release_id, details in new_releases.items()}
    doc_ref.set(update_data, merge=True)
    print(f"Successfully stored {len(new_releases)} new releases in Firestore.")


def publish_to_pubsub(space_id, release):
    """Publishes a message to Pub/Sub with space ID and release details."""
    message_json = json.dumps({"space_id": space_id, "release": release}).encode(
        "utf-8"
    )
    future = publisher.publish(topic_path, message_json)
    future.add_done_callback(callback)
    publish_futures.append(future)


def send_new_release_notifications():
    """Main function to check for, summarize, and send new release notifications."""
    all_releases_map = {}
    with futures.ThreadPoolExecutor() as executor:
        results = executor.map(get_releases_from_rss, rss_urls)
        for release_map in results:
            all_releases_map.update(release_map)

    new_releases_map = get_new_releases(all_releases_map)

    if not new_releases_map:
        print("No new releases found.")
        return

    # Process and summarize new releases
    for release_id, release_details in new_releases_map.items():
        print(
            f"New release found: {release_details['repo_name']} {release_details['title']}"
        )
        print("Generating AI summary...")

        summary = summarize_release_notes(
            release_details.get("content", ""), release_details.get("title", "")
        )
        release_details["summary"] = summary
        del release_details["content"]
        print(f"Summary for {release_details['title']}:\n{summary}")

    # Send notifications and store results
    subscriptions_ref = firestore_client.collection("github_repo_subscriptions")
    for release_id, release in new_releases_map.items():
        repo_doc = subscriptions_ref.document(release["repo_name"]).get()
        if repo_doc.exists:
            spaces_subscribed = repo_doc.to_dict().get("spaces_subscribed", [])
            for space in spaces_subscribed:
                publish_to_pubsub(space, release)
                print(
                    f"Published notification for {release['repo_name']} to space {space}"
                )

    store_new_releases(new_releases_map)

    if publish_futures:
        futures.wait(publish_futures, return_when=futures.ALL_COMPLETED)
        print("All publish futures completed.")


# --- Cloud Function Entry Point ---
@functions_framework.http
def http_request(request):
    """HTTP-triggered Cloud Function entry point."""
    try:
        send_new_release_notifications()
        return ("Processing complete.", 200)
    except Exception as e:
        print(f"An error occurred during execution: {e}")
        return ("An internal error occurred.", 500)
