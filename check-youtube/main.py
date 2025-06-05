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
from channel_rss_urls import rss_urls

firestore_client = firestore.Client(project=os.environ.get("GCP_PROJECT_ID"))
batch_settings = pubsub_v1.types.BatchSettings(
    max_messages=100,  # default 100
    max_bytes=1024,  # default 1 MB
    max_latency=1,  # default 10 ms
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


def get_videos_from_rss(rss_url):
    """Parses a YouTube RSS feed and returns a map of recent videos."""
    try:
        page = requests.get(rss_url)
        page.raise_for_status()  # Raise an exception for bad status codes
        soup = BeautifulSoup(page.content, "xml")
        channel_id = soup.find("yt:channelId").text
        channel_name = soup.find("author").find("name").text
        video_map = {}
        videos = soup.find_all("entry")
        for video in videos:
            video_id = video.find("yt:videoId").text
            pub_date_str = video.find("published").text
            pub_date = (
                datetime.fromisoformat(pub_date_str)
                .astimezone(timezone("US/Central"))
                .date()
            )
            today_date = datetime.now(timezone("US/Central")).date()

            if pub_date == today_date:
                video_map[video_id] = {
                    "channel_name": channel_name,
                    "channel_id": channel_id,
                    "title": video.find("title").text,
                    "link": video.find("link")["href"],
                    "date": pub_date.strftime("%B %d, %Y"),
                }
        return video_map
    except requests.exceptions.RequestException as e:
        print(f"Error fetching RSS feed {rss_url}: {e}")
        return {}
    except Exception as e:
        print(f"Error parsing RSS feed {rss_url}: {e}")
        return {}


def get_stored_videos():
    """Retrieves the map of already processed videos from Firestore."""
    doc_ref = firestore_client.collection("youtube_video_updates").document("videos")
    doc = doc_ref.get()
    return doc.to_dict() if doc.exists else {}


def get_new_videos(video_map=None):
    """Compares fetched videos with stored videos to find new ones."""
    if video_map is None:
        return {}
    stored_video_map = get_stored_videos()
    new_videos_map = {}
    for video_id, video_details in video_map.items():
        if video_id not in stored_video_map:
            new_videos_map[video_id] = video_details
    return new_videos_map


def publish_to_pubsub(space_id, video):
    """Publishes a message to Pub/Sub with space ID and video details."""
    message_json = json.dumps(
        {
            "space_id": space_id,
            "video": video,
        }
    ).encode("utf-8")
    future = publisher.publish(topic_path, message_json)
    future.add_done_callback(callback)
    publish_futures.append(future)
    print(f"Published message for video: {video['title']}")


def send_new_video_notifications():
    """Main function to check for and send new video notifications."""
    all_videos_map = {}
    with futures.ThreadPoolExecutor() as executor:
        # Process each RSS URL in parallel
        results = executor.map(get_videos_from_rss, rss_urls)
        for video_map in results:
            all_videos_map.update(video_map)

    new_videos_map = get_new_videos(all_videos_map)
    subscriptions_ref = firestore_client.collection("youtube_channel_subscriptions")

    for video_id, video in new_videos_map.items():
        print(f"New video found: {video['title']} from {video['channel_name']}")
        # Use channel_id for more reliable document matching
        channel_doc = subscriptions_ref.document(video["channel_name"]).get()
        if channel_doc.exists:
            spaces_subscribed = channel_doc.to_dict().get("spaces_subscribed", [])
            for space_id in spaces_subscribed:
                publish_to_pubsub(space_id, video)
        else:
            print(f"No subscriptions found for channel ID: {video['channel_name']}")

    # Wait for all Pub/Sub messages to be published
    futures.wait(publish_futures, return_when=futures.ALL_COMPLETED)

    # If there were new videos, update the Firestore document with all videos
    # found today to prevent duplicate notifications.
    if new_videos_map:
        doc_ref = firestore_client.collection("youtube_video_updates").document(
            "videos"
        )
        # We merge with existing stored videos to keep a running list
        stored_videos = get_stored_videos()
        stored_videos.update(all_videos_map)
        doc_ref.set(stored_videos)
        print("Firestore updated with the latest videos.")


@functions_framework.http
def http_request(request):
    """HTTP Cloud Function trigger."""
    send_new_video_notifications()
    return ("Done", 200)