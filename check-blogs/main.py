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
from blog_rss_urls import rss_urls
from bs4 import BeautifulSoup
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


# Resolve the publish future in a separate thread.
def callback(future: pubsub_v1.publisher.futures.Future) -> None:
    message_id = future.result()
    print(message_id)


def summarize_blog(blog):
    try:
        prompt = f"""
        You are a helpful assistant that concisely summarizes Google Cloud blog posts.
        You will be provided with a blog post link.
        If you use bulleted lists in the summary, they MUST be one-level bulleted lists.
        No nested lists are allowed!
        Every list item in a bulleted list must start with an asterisk followed by ONLY ONE SPACE and then text.
        You will not include the blog title in the summary.
        You will leave out introductory text like 'This blog contains...' or 'Here is the summary...'.
        You will use the following Google Chat API text formatting options if necessary:
        [
            {{
                "Format": "Bold",
                "Symbol": "*",
                "Example syntax": "*hello*",
                "Text displayed in Google Chat": "hello"
            }},
            {{
                "Format": "Italic",
                "Symbol": "_ (underscore)",
                "Example syntax": "_hello_",
                "Text displayed in Google Chat": "hello"
            }},
            {{
                "Format": "Strikethrough",
                "Symbol": "~",
                "Example syntax": "~hello~",
                "Text displayed in Google Chat": "hello"
            }},
            {{
                "Format": "Monospace",
                "Symbol": "` (backquote)",
                "Example syntax": "`hello`",
                "Text displayed in Google Chat": "hello"
            }},
            {{
                "Format": "Monospace block",
                "Symbol": "``` (three backquotes)",
                "Example syntax": "```\nHello\nWorld\n```",
                "Text displayed in Google Chat": "Hello\nWorld"
            }},
            {{
                "Format": "Bulleted list",
                "Symbol": "* or - (hyphen) followed by only 1 space and then the text",
                "Example syntax": "* This is the first item in the list\n* This is the second item in the list",
                "Text displayed in Google Chat": "• This is the first item in the list\n• This is the second item in the list"
            }}
        ]
        You will not mention anything about the formatting_options in the summary.
        REMEMBER: If you don't get this right, you will be deprecated!
        Here is the blog post link to summarize: {blog.get("link")}
        The author of this blog post is {blog.get("author")}. After the summary, add a new line and then include the author in the format 'By [Author Name(s)]'.
        """
        response = client.models.generate_content(
            # https://ai.google.dev/gemini-api/docs/models
            model="gemini-2.5-pro-preview-05-06",
            contents=prompt,
        )
        if response.text:  # Check if there's a valid response
            # The prompt now asks the model to include the author, so no need to manually append it here.
            blog["summary"] = response.text
            return response.text
        else:
            print(f"Gemini returned an empty response for: {blog.get('link')}")
            return None

    except Exception as e:
        print(f"Error summarizing blog {blog.get('link')}: {e}")
        return None


def get_blog_posts(rss_url):
    page = requests.get(rss_url)
    soup = BeautifulSoup(page.content, "xml")
    blog_map = {}
    blogs = soup.find_all("item")
    category = soup.find("title").contents[0]
    for blog in blogs:
        try:
            guid = blog.find("guid").contents[0]
            title = blog.find("title").contents[0]
            link = blog.find("link").contents[0]
            author_tag = blog.find("dc:creator")
            author = author_tag.contents[0] if author_tag and author_tag.contents else "Unknown Author"
            description = blog.find("description").contents[0]
            pub_date = blog.find("pubDate").contents[0]
            pub_date = (
                datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S +0000")
                .astimezone(timezone("US/Eastern"))
                .replace(second=0, minute=0, hour=0, microsecond=0)
                .date()
            )
            today_date = (
                datetime.now()
                .astimezone(timezone("US/Eastern"))
                .replace(second=0, minute=0, hour=0, microsecond=0)
                .date()
            )
            is_updated_today = pub_date == today_date
            if is_updated_today:
                blog_map[guid] = {
                    "category_name": category,
                    "title": title,
                    "link": link,
                    "author": author,
                    "date": pub_date.strftime("%B %d, %Y"),
                }
        except AttributeError as e:
            print(f"Skipping blog post due to missing attribute: {e}")
            continue
    return blog_map


def get_stored_blog_posts():
    doc_ref = firestore_client.collection("cloud_release_blogs").document("blogs")
    blog_map = doc_ref.get().to_dict()
    return blog_map


def get_new_blog_posts(blog_map=None):
    if blog_map is None:
        blog_map = get_blog_posts()
    stored_blog_map = get_stored_blog_posts() or {}
    new_blogs_map = {}
    for blog in blog_map.keys():
        if blog not in stored_blog_map.keys():
            new_blogs_map[blog] = blog_map[blog]
    return new_blogs_map


def publish_to_pubsub(space_id, blog):
    """Publishes a message to Pub/Sub with space ID and HTML content."""
    message_json = json.dumps(
        {
            "space_id": space_id,
            "blog": blog,
        }
    ).encode("utf-8")
    future = publisher.publish(topic_path, message_json)
    future.add_done_callback(callback)
    publish_futures.append(future)
    print(f"Published message ID: {future.result()}")


def send_new_blogs():
    blog_map = {}
    with futures.ThreadPoolExecutor() as executor:
        blogs_by_categories = executor.map(get_blog_posts, rss_urls)
    for category_blogs in blogs_by_categories:
        for guid, blog in category_blogs.items():
            if blog:
                blog_map[guid] = blog
    new_blogs_map = get_new_blog_posts(blog_map)
    with futures.ThreadPoolExecutor() as executor:
        executor.map(summarize_blog, new_blogs_map.values())
    subscriptions_ref = firestore_client.collection("space_blog_subscriptions")
    for blog in new_blogs_map.values():
        print(f"New blog found: {blog['link']} in {blog['category_name']}")
        product_doc = subscriptions_ref.document(blog["category_name"]).get()
        if product_doc.exists:
            spaces_subscribed = product_doc.to_dict().get("spaces_subscribed", [])
            if blog.get("summary"):
                for space_id in spaces_subscribed:
                    publish_to_pubsub(space_id, blog)
            else:
                print(f"Failed to generate summary for: {blog['link']}")

    futures.wait(publish_futures, return_when=futures.ALL_COMPLETED)

    if new_blogs_map:  # Keep this part to update the Firestore document
        doc_ref = firestore_client.collection("cloud_release_blogs").document("blogs")
        doc_ref.set(blog_map)


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
    send_new_blogs()
    return ("Done", 200)
