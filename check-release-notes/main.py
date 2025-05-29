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
from hashlib import sha256

import functions_framework
import requests
from bs4 import BeautifulSoup
from google.cloud import firestore, pubsub_v1
from product_rss_urls import rss_urls
from pytz import timezone

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
firestore_client = firestore.Client(project=os.environ.get("GCP_PROJECT_ID"))


def remove_libraries(html):
    """
    Remove the libraries section (e.g. <h3>Libraries</h3>...) from the release notes
    because this section tends to be very verbose and doesn't display well in Chat.
    Replace it with a generic <h3>Libraries Updated</h3> section.
    Args:
        html: The html from which to remove the libraries section
    Returns:
        The html with the libraries section removed
    """
    if re.search(r"<h3>Libraries</h3>(.|\n)*?<h3>", html):
        html = re.sub(
            r"<h3>Libraries</h3>(.|\n)*?<h3>", "<h3>Libraries Updated</h3>\n<h3>", html
        )
    elif "<h3>Libraries</h3>" in html:
        # This is the case where the libraries section is the last section
        # so there won't be a <h3> tag after it
        html = re.sub(r"<h3>Libraries</h3>(.|\n)*", "<h3>Libraries Updated</h3>", html)
    return html


def get_todays_release_note(rss_url):
    """
    Parses a product release notes RSS feed and returns the latest release note.

    Args:
        rss_url (str): The URL of the RSS feed.

    Returns:
        str: The title and description of the latest release note, or None if an error occurs.
    """
    try:
        response = requests.get(rss_url)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        soup = BeautifulSoup(response.content, "xml")
        product = re.sub(
            " - release notes", "", soup.find("title").contents[0], flags=re.IGNORECASE
        )
        item = soup.find("entry") or soup.find("item")
        if item:
            if item.find("updated"):
                updated = item.find("updated").contents[0]
                updated_date = datetime.strptime(
                    updated.split("T")[0], "%Y-%m-%d"
                ).date()
            elif item.find("pubDate"):
                updated = item.find("pubDate").contents[0]
                updated_date = datetime.strptime(
                    updated.split(", ")[1].strip(), "%d %b %Y %X %Z"
                ).date()
            # Get the release note content
            release_note = item.find("content") or item.find("description")
            release_note = release_note.contents[0]
            release_note = remove_libraries(release_note)
            link = item.find("link").get("href") or item.find("link").contents[0]

            today_date = (
                datetime.now()
                .astimezone(timezone("US/Eastern"))
                .replace(second=0, minute=0, hour=0, microsecond=0)
                .date()
            )
            is_updated_today = updated_date == today_date
            if is_updated_today:
                return dict(
                    product=product,
                    date=updated_date.strftime("%B %d, %Y"),
                    link=link,
                    html=release_note,
                    rss_url=rss_url,
                )
        return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching {rss_url}: {e}")
        return None
    except AttributeError as e:
        print(f"Error parsing {rss_url}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while fetching {rss_url}: {e}")
        return None


def get_new_release_note_subsections(latest_release_note, stored_release_note):
    """
    Get the new release note subsections by comparing the new release note with the stored release note.
    Subsections are defined as any section that starts with <h3> header.
    Args:
        new_release_note: The new release note
        stored_release_note: The stored release note
    Returns:
        The new release note subsections
    """
    latest_release_note_subsections_html = re.split(
        r"\<h3\>.*?\<\/h3\>", latest_release_note.get("html")
    )[1:]
    latest_release_note_subsections_text_only = [
        BeautifulSoup(html, "html.parser").get_text()
        for html in latest_release_note_subsections_html
    ]
    latest_release_note_subsections_headers = re.findall(
        r"<h3>(.*)?</h3>", latest_release_note.get("html")
    )
    stored_release_note_subsections_html = re.split(
        r"\<h3\>.*?\<\/h3\>", stored_release_note.get("html")
    )[1:]
    stored_release_note_subsections_text_only = [
        BeautifulSoup(html, "html.parser").get_text()
        for html in stored_release_note_subsections_html
    ]
    # Get only new subsections from the latest release note
    new_release_notes_subsections = ""
    for index, subsection_text in enumerate(latest_release_note_subsections_text_only):
        if subsection_text not in stored_release_note_subsections_text_only:
            new_release_notes_subsections += f"<h3>{latest_release_note_subsections_headers[index]}</h3>{latest_release_note_subsections_html[index]}"
    latest_release_note["html"] = new_release_notes_subsections
    return latest_release_note


def get_new_release_notes(latest_release_notes):
    new_release_notes = {}
    for product in latest_release_notes:
        doc_ref = firestore_client.collection("cloud_release_notes").document(
            product.replace("/", "")
        )
        stored_release_note = doc_ref.get().to_dict()
        if stored_release_note and stored_release_note.get("html"):
            if isNewRelease(
                latest_release_notes.get(product),
                stored_release_note,
            ):
                save_release_note_to_firestore(
                    product, latest_release_notes.get(product)
                )
                new_release_note_subsections = get_new_release_note_subsections(
                    latest_release_notes.get(product), stored_release_note
                )
                # Sometimes a new release note is actually a retraction of a subsection within the release note.
                # The following checks if the html field is populated before adding it to new_release_notes
                # so that users are not alerted for a retraction.
                if new_release_note_subsections.get("html"):
                    new_release_notes[product] = new_release_note_subsections
        else:
            save_release_note_to_firestore(product, latest_release_notes.get(product))
            new_release_notes[product] = latest_release_notes.get(product)
    return new_release_notes


def isNewRelease(latest_release_note, stored_release_note):
    """
    Check if anything in the release notes is new by comparing the sha256 hash of the release notes
    taken from the release notes page and the stored release notes which are stored in
    the Firestore database.
    Args:
        latest_release_notes: The latest release notes for all products
        stored_release_notes: The stored release notes for all products
    Returns:
        True if the release notes are new, False otherwise
    """
    stored_release_note_text_only = BeautifulSoup(
        stored_release_note.get("html"), "html.parser"
    ).get_text()
    latest_release_note_text_only = BeautifulSoup(
        latest_release_note.get("html"), "html.parser"
    ).get_text()
    return (
        sha256(latest_release_note_text_only.encode("utf-8")).digest()
        != sha256(stored_release_note_text_only.encode("utf-8")).digest()
    )


def save_release_note_to_firestore(product, new_release):
    doc_ref = firestore_client.collection("cloud_release_notes").document(
        product.replace("/", "")
    )
    doc_ref.set(new_release)


def publish_to_pubsub(space_id, release_note):
    """Publishes a message to Pub/Sub with space ID and HTML content."""
    message_json = json.dumps(
        {
            "space_id": space_id,
            "release_note": release_note,
        }
    ).encode("utf-8")
    future = publisher.publish(topic_path, message_json)
    # Non-blocking. Allow the publisher client to batch multiple messages.
    future.add_done_callback(callback)
    publish_futures.append(future)
    print(f"Published message ID: {future.result()}")


# Resolve the publish future in a separate thread.
def callback(future: pubsub_v1.publisher.futures.Future) -> None:
    message_id = future.result()
    print(message_id)


# To deploy the function, run the following command:
# functions-framework --target=http_request
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
    todays_release_notes_dict = {}
    with futures.ThreadPoolExecutor() as executor:
        todays_release_notes = executor.map(get_todays_release_note, rss_urls)
    for release_note in todays_release_notes:
        if release_note:
            todays_release_notes_dict[release_note["product"]] = release_note
    new_release_notes_only = get_new_release_notes(todays_release_notes_dict)
    if new_release_notes_only:
        print(f"Found new release notes: {new_release_notes_only}")
        # Get spaces subscribed to the products with new release notes
        subscriptions_ref = firestore_client.collection("space_product_subscriptions")
        for product, release_note in new_release_notes_only.items():
            product_doc = subscriptions_ref.document(product.replace("/", "")).get()
            if product_doc.exists:
                spaces_subscribed = product_doc.to_dict().get("spaces_subscribed", [])
                for space_id in spaces_subscribed:
                    publish_to_pubsub(space_id, release_note)
        futures.wait(publish_futures, return_when=futures.ALL_COMPLETED)
    else:
        print("No new release notes")
    return ("Done", 200)
