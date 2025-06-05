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

import base64
import json
import os
import re
from concurrent import futures
from typing import Any, Mapping

import client_utils
import flask
import functions_framework
from google.apps.chat_v1.types import Message
from google.cloud import firestore
from markdownify import MarkdownConverter

SUBSCRIBE_COMMAND_ID = 1
SUBSCRIPTIONS_COMMAND_ID = 2
# YOUTUBE-UPDATE: A new command ID for YouTube specific subscriptions if needed,
# or you can just rely on the main /subscribe dialog.
# For now, we will just add it to the main dialog.

DB = firestore.Client(os.environ.get("GCP_PROJECT_ID"))


@functions_framework.http
def chat_app(req: flask.Request) -> Mapping[str, Any]:
    req_json = req.get_json()
    print(f"Received request: {req_json}")
    # Handle chat UI
    if req.method == "POST" and req.path == "/":
        chatEvent = req_json["chat"]
        if "messagePayload" in chatEvent:
            return handleMessage(req_json)
        # Handle app commands
        elif "appCommandPayload" in chatEvent:
            appCommandMetadata = chatEvent["appCommandPayload"]["appCommandMetadata"]
            if appCommandMetadata["appCommandType"] == "SLASH_COMMAND":
                if appCommandMetadata["appCommandId"] == SUBSCRIBE_COMMAND_ID:
                    return openInitialDialog(req_json)
                elif appCommandMetadata["appCommandId"] == SUBSCRIPTIONS_COMMAND_ID:
                    return returnSubscriptions(req_json)
        # Handle added to space
        elif "addedToSpacePayload" in chatEvent:
            return handleMessage(req_json)
        # Handle app removal from space
        elif "removedFromSpacePayload" in chatEvent:
            print("Unsubscribing from space")
            space_id = req_json["chat"]["removedFromSpacePayload"]["space"]["name"]
            subscriptions_ref = DB.collection("product_space_subscriptions")
            product_doc_ref = subscriptions_ref.document(space_id.replace("/", "_"))
            products_doc = product_doc_ref.get()
            if products_doc.exists:
                doc_dict = products_doc.to_dict()
                products = doc_dict.get("products_subscribed", [])
                categories = doc_dict.get("categories_subscribed", [])
                # YOUTUBE-UPDATE: Get subscribed youtube channels to properly unsubscribe
                youtube_channels = doc_dict.get("youtube_channels_subscribed", [])
                with futures.ThreadPoolExecutor() as executor:
                    unsubscribe_space_product_futures = [
                        executor.submit(
                            unsubscribe_space_product,
                            space_id,
                            DB.collection("space_product_subscriptions"),
                            product,
                        )
                        for product in products
                    ]
                    unsubscribe_space_blogs_futures = [
                        executor.submit(
                            unsubscribe_space_blogs,
                            space_id,
                            DB.collection("space_blog_subscriptions"),
                            category,
                        )
                        for category in categories
                    ]
                    # YOUTUBE-UPDATE: Unsubscribe from youtube channels
                    unsubscribe_space_youtube_futures = [
                        executor.submit(
                            unsubscribe_space_youtube,
                            space_id,
                            DB.collection("youtube_channel_subscriptions"),
                            channel_name,
                        )
                        for channel_name in youtube_channels
                    ]
                futures.wait(
                    unsubscribe_space_product_futures
                    + unsubscribe_space_blogs_futures
                    + unsubscribe_space_youtube_futures # YOUTUBE-UPDATE
                )
                product_doc_ref.delete()
                print(
                    f"Unsubscribed space {space_id} from all products, categories, and channels."
                )
            return ("Done", 200)
        # Handle button clicks
        elif "buttonClickedPayload" in chatEvent:
            if (
                req_json["commonEventObject"]["parameters"]["actionName"]
                == "openInitialDialog"
            ):
                return openInitialDialog(req_json)
            elif (
                req_json["commonEventObject"]["parameters"]["actionName"]
                == "submitDialog"
            ):
                return submitDialog(req_json)
    # Handle Pub/Sub push messages
    elif req.method == "POST" and req.path == "/messages":
        return handle_pubsub_message(req)
    print("Reached an unexpected state.")


def handleMessage(event):
    return {
        "hostAppDataAction": {
            "chatDataAction": {
                "createMessageAction": {
                    "message": {
                        "text": "To add a subscription in this space, use the `/subscribe` command!",
                    }
                }
            }
        }
    }


CATEGORY_MAP = {
    "All Data Products": client_utils.google_cloud_data_products,
    "All AI Products": client_utils.google_cloud_ai_products,
    "All App Mod Products": client_utils.google_cloud_app_mod_products,
    "All Security Products": client_utils.google_cloud_security_products,
}

BLOG_CATEGORY_MAP = {
    "All Data Blogs": getattr(client_utils, "data_categories", []),
}

# YOUTUBE-UPDATE: Add a map for YouTube channels.
# This assumes you have a list of all channel names in client_utils.py
YOUTUBE_CHANNEL_MAP = {
    "All YouTube Channels": getattr(client_utils, "channels", []),
}


def _get_expanded_subscription_set(subscribed_items, category_map):
    initial_set = set(subscribed_items)
    expanded_set = set(initial_set)

    for category_tag, category_list in category_map.items():
        if category_tag in initial_set:
            expanded_set.update(category_list)

    return expanded_set


def get_members_only(category_tag, category_map):
    full_list = category_map.get(category_tag, [])
    return {str(item) for item in full_list if str(item) != str(category_tag)}


def openInitialDialog(request_json):
    try:
        # Default empty sets
        products_subscribed_set = set()
        categories_subscribed_set = set()
        youtube_channels_subscribed_set = set() # YOUTUBE-UPDATE
        doc_exists = False

        space_name = request_json["chat"]["appCommandPayload"]["space"]["name"].replace("/", "_")
        subscriptions_ref = DB.collection("product_space_subscriptions")
        product_doc_ref = subscriptions_ref.document(space_name)
        products_doc = product_doc_ref.get()
        doc_exists = products_doc.exists

        if doc_exists:
            doc_data = products_doc.to_dict()
            products_subscribed_set = set(doc_data.get("products_subscribed", []))
            categories_subscribed_set = set(doc_data.get("categories_subscribed", []))
            # YOUTUBE-UPDATE: Get youtube channel subscriptions
            youtube_channels_subscribed_set = set(doc_data.get("youtube_channels_subscribed", []))


        all_products_override = "All Products" in products_subscribed_set
        all_blogs_override = "All Blogs" in categories_subscribed_set
        # YOUTUBE-UPDATE: Check for YouTube override
        all_youtube_override = "All YouTube Channels" in youtube_channels_subscribed_set

        # --- Generate Product Dialog Items (No changes here) ---
        notes = []
        all_possible_products = getattr(client_utils, "google_cloud_products", [])
        # ... (logic for notes remains the same)
        if all_products_override:
            for product in all_possible_products:
                is_selected = product == "All Products"
                notes.append({"text": product, "value": product, "selected": is_selected})
        elif doc_exists:
            active_product_tags = {tag for tag in CATEGORY_MAP if tag in products_subscribed_set}
            products_covered_by_active_tags = set().union(*(get_members_only(tag, CATEGORY_MAP) for tag in active_product_tags))
            for product in all_possible_products:
                is_selected = product in active_product_tags or (product in products_subscribed_set and product not in products_covered_by_active_tags)
                notes.append({"text": product, "value": product, "selected": is_selected})
        else:
            for product in all_possible_products:
                notes.append({"text": product, "value": product, "selected": False})


        # --- Generate Blog Dialog Items (No changes here) ---
        blogs = []
        all_possible_categories = getattr(client_utils, "categories", [])
        # ... (logic for blogs remains the same)
        if all_blogs_override:
            for category in all_possible_categories:
                is_selected = category == "All Blogs"
                blogs.append({"text": category, "value": category, "selected": is_selected})
        elif doc_exists:
            active_blog_tags = {tag for tag in BLOG_CATEGORY_MAP if tag in categories_subscribed_set}
            blogs_covered_by_active_tags = set().union(*(get_members_only(tag, BLOG_CATEGORY_MAP) for tag in active_blog_tags))
            for category in all_possible_categories:
                is_selected = category in active_blog_tags or (category in categories_subscribed_set and category not in blogs_covered_by_active_tags)
                blogs.append({"text": category, "value": category, "selected": is_selected})
        else:
            for category in all_possible_categories:
                blogs.append({"text": category, "value": category, "selected": False})


        # YOUTUBE-UPDATE: --- Generate YouTube Channel Dialog Items ---
        youtube_channels = []
        all_possible_youtube_channels = getattr(client_utils, "youtube_channels", [])

        if all_youtube_override:
            for channel in all_possible_youtube_channels:
                is_selected = channel == "All YouTube Channels"
                youtube_channels.append(
                    {"text": channel, "value": channel, "selected": is_selected}
                )
        elif doc_exists:
            active_youtube_tags = {
                tag for tag in YOUTUBE_CHANNEL_MAP if tag in youtube_channels_subscribed_set
            }
            channels_covered_by_tags = set().union(*(get_members_only(tag, YOUTUBE_CHANNEL_MAP) for tag in active_youtube_tags))
            for channel in all_possible_youtube_channels:
                is_selected = channel in active_youtube_tags or (channel in youtube_channels_subscribed_set and channel not in channels_covered_by_tags)
                youtube_channels.append(
                    {"text": channel, "value": channel, "selected": is_selected}
                )
        else:
            # No document exists and no override, nothing is selected
            for channel in all_possible_youtube_channels:
                youtube_channels.append(
                    {"text": channel, "value": channel, "selected": False}
                )

        # YOUTUBE-UPDATE: Pass the new youtube_channels list to the dialog response
        return client_utils.retrieve_dialog_response(notes, blogs, youtube_channels)

    except Exception as e:
        print(f"Error opening initial dialog: {e}")
        # Fallback with empty lists
        notes = [{"text": p, "value": p, "selected": False} for p in getattr(client_utils, "google_cloud_products", [])]
        blogs = [{"text": c, "value": c, "selected": False} for c in getattr(client_utils, "categories", [])]
        youtube_channels = [{"text": y, "value": y, "selected": False} for y in getattr(client_utils, "youtube_channels", [])]
        return client_utils.retrieve_dialog_response(
            notes, blogs, youtube_channels, error="Failed to load subscriptions."
        )


def returnSubscriptions(request_json):
    subscriptions_ref = DB.collection("product_space_subscriptions")
    product_doc_ref = subscriptions_ref.document(
        request_json["chat"]["appCommandPayload"]["space"]["name"].replace("/", "_")
    )
    products_doc = product_doc_ref.get()
    if products_doc.exists:
        doc_dict = products_doc.to_dict()
        products = doc_dict.get("products_subscribed", [])
        categories = doc_dict.get("categories_subscribed", [])
        # YOUTUBE-UPDATE: Get youtube subscriptions
        youtube_channels = doc_dict.get("youtube_channels_subscribed", [])

        product_list = "\n".join(f"- {p}" for p in products) if products else "None"
        category_list = "\n".join(f"- {c}" for c in categories) if categories else "None"
        # YOUTUBE-UPDATE: Create list of youtube subscriptions
        youtube_list = "\n".join(f"- {y}" for y in youtube_channels) if youtube_channels else "None"

        # YOUTUBE-UPDATE: Add YouTube channels to the message
        message_text = (f"Current Subscriptions for this Space:\n\n"
                        f"*Products:*\n{product_list}\n\n"
                        f"*Blog categories:*\n{category_list}\n\n"
                        f"*YouTube Channels:*\n{youtube_list}")

        return {"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": {"text": message_text}}}}}
    else:
        return {"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": {"text": "There are no subscriptions for this space yet. Use `/subscribe` to add some!"}}}}}


def handle_templatized_notes_inputs(products):
    initial_products_set = set(products)
    if "All Products" in initial_products_set:
        return sorted(list(set(client_utils.google_cloud_products))), True
    final_products_set = set(initial_products_set)
    for category_tag, category_product_list in CATEGORY_MAP.items():
        if category_tag in initial_products_set:
            final_products_set.update(category_product_list)
    return sorted(list(final_products_set)), False


def handle_templatized_blogs_inputs(categories):
    initial_categories_set = set(categories)
    if "All Blogs" in initial_categories_set:
        return sorted(list(set(client_utils.categories))), True
    final_categories_set = set(initial_categories_set)
    for category_tag, category_list in BLOG_CATEGORY_MAP.items():
        if category_tag in initial_categories_set:
            final_categories_set.update(category_list)
    return sorted(list(final_categories_set)), False

# YOUTUBE-UPDATE: Add a handler for YouTube channel inputs
def handle_templatized_youtube_inputs(channels):
    initial_channels_set = set(channels)
    if "All YouTube Channels" in initial_channels_set:
        # Assumes client_utils.youtube_channels contains all channel names including the "All" tag
        return sorted(list(set(client_utils.youtube_channels))), True
    # No other templating for youtube channels, just return the list
    return sorted(list(initial_channels_set)), False


def submitDialog(event):
    chatUser = event["chat"]["user"]
    products = []
    categories = []
    youtube_channels = [] # YOUTUBE-UPDATE
    all_products = False
    all_blogs = False
    all_youtube = False # YOUTUBE-UPDATE
    space_id = event["chat"]["buttonClickedPayload"]["space"]["name"]

    if "formInputs" in event["commonEventObject"]:
        form_inputs = event["commonEventObject"]["formInputs"]
        if "contactType" in form_inputs:
            products = form_inputs["contactType"]["stringInputs"]["value"]
            products, all_products = handle_templatized_notes_inputs(products)
        if "blogType" in form_inputs:
            categories = form_inputs["blogType"]["stringInputs"]["value"]
            categories, all_blogs = handle_templatized_blogs_inputs(categories)
        # YOUTUBE-UPDATE: Process youtube channel form inputs
        if "youtubeChannelType" in form_inputs:
            youtube_channels = form_inputs["youtubeChannelType"]["stringInputs"]["value"]
            youtube_channels, all_youtube = handle_templatized_youtube_inputs(youtube_channels)

    with futures.ThreadPoolExecutor() as executor:
        record_space_subscription_futures = [
            executor.submit(record_space_subscription, space_id, product)
            for product in products
        ]
        record_space_blogs_futures = [
            executor.submit(record_space_blogs, space_id, category)
            for category in categories
        ]
        # YOUTUBE-UPDATE: Record youtube channel subscriptions
        record_space_youtube_futures = [
            executor.submit(record_space_youtube_subscription, space_id, channel)
            for channel in youtube_channels
        ]
    futures.wait(
        record_space_subscription_futures
        + record_space_blogs_futures
        + record_space_youtube_futures # YOUTUBE-UPDATE
    )
    # YOUTUBE-UPDATE: Pass youtube_channels to the recording function
    record_product_subscription(space_id, products, categories, youtube_channels)

    # YOUTUBE-UPDATE: Update response message logic
    product_message = "All Products" if all_products else (f"products: {', '.join(products)}" if products else "no products")
    category_message = "All Blog Categories" if all_blogs else (f"blog categories: {', '.join(categories)}" if categories else "no blog categories")
    youtube_message = "All YouTube Channels" if all_youtube else (f"YouTube channels: {', '.join(youtube_channels)}" if youtube_channels else "no YouTube channels")

    if products or categories or youtube_channels:
        response = f"😄🎉 Your request has been successfully submitted!\n\nThis space is now subscribed to:\n- {product_message}\n- {category_message}\n- {youtube_message}"
    else:
        response = "😄🎉 Your request has been successfully submitted!\n\nThis space is now unsubscribed from all products, blogs, and channels."

    return {"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": {"privateMessageViewer": chatUser, "text": response}}}}}


# YOUTUBE-UPDATE: New function to record subscriptions to the youtube inverted index
def record_space_youtube_subscription(space_id, channel_name):
    try:
        # Assumes you have a map from channel name to channel ID in client_utils
        # to ensure stable document IDs in Firestore.
        channel_id = client_utils.youtube_channel_details.get(channel_name, {}).get("id")
        if not channel_id:
            print(f"Error: Channel ID not found for channel name '{channel_name}'")
            return

        subscriptions_ref = DB.collection("youtube_channel_subscriptions")
        channel_doc_ref = subscriptions_ref.document(channel_id)
        channel_doc = channel_doc_ref.get()

        if channel_doc.exists:
            spaces_subscribed = channel_doc.to_dict().get("spaces_subscribed", [])
            if space_id not in spaces_subscribed:
                spaces_subscribed.append(space_id)
                channel_doc_ref.update({"spaces_subscribed": spaces_subscribed})
        else:
            channel_doc_ref.set({"channel_name": channel_name, "spaces_subscribed": [space_id]})
    except Exception as e:
        print(f"Error recording youtube subscription for '{channel_name}': {e}", exc_info=True)


def record_space_blogs(space_id, category):
    try:
        subscriptions_ref = DB.collection("space_blog_subscriptions")
        category_doc_ref = subscriptions_ref.document(category)
        category_doc = category_doc_ref.get()
        if category_doc.exists:
            spaces_subscribed = category_doc.to_dict().get("spaces_subscribed", [])
            if space_id not in spaces_subscribed:
                spaces_subscribed.append(space_id)
                category_doc_ref.update({"spaces_subscribed": spaces_subscribed})
        else:
            category_doc_ref.set({"category": category, "spaces_subscribed": [space_id]})
    except Exception as e:
        print(f"Error recording subscription: {e}", exc_info=True)


def record_space_subscription(space_id, product):
    try:
        subscriptions_ref = DB.collection("space_product_subscriptions")
        product_doc_ref = subscriptions_ref.document(product.replace("/", ""))
        product_doc = product_doc_ref.get()
        if product_doc.exists:
            spaces_subscribed = product_doc.to_dict().get("spaces_subscribed", [])
            if space_id not in spaces_subscribed:
                spaces_subscribed.append(space_id)
                product_doc_ref.update({"spaces_subscribed": spaces_subscribed})
        else:
            product_doc_ref.set({"product": product, "spaces_subscribed": [space_id]})
    except Exception as e:
        print(f"Error recording subscription: {e}", exc_info=True)


# YOUTUBE-UPDATE: New function to unsubscribe a space from a youtube channel
def unsubscribe_space_youtube(space_id, space_youtube_subscriptions_ref, channel_name):
    print(f"Unsubscribing space {space_id} from YouTube Channel {channel_name}")
    channel_id = client_utils.youtube_channel_details.get(channel_name, {}).get("id")
    if not channel_id:
        print(f"Could not find channel ID for {channel_name} to unsubscribe.")
        return
    channel_doc_ref = space_youtube_subscriptions_ref.document(channel_id)
    channel_doc_ref.update({"spaces_subscribed": firestore.ArrayRemove([space_id])})


def unsubscribe_space_blogs(space_id, space_blog_subscriptions_ref, category):
    print(f"Unsubscribing space {space_id} from category {category}")
    categories_doc_ref = space_blog_subscriptions_ref.document(category)
    categories_doc_ref.update({"spaces_subscribed": firestore.ArrayRemove([space_id])})


def unsubscribe_space_product(space_id, space_product_subscriptions_ref, product):
    print(f"Unsubscribing space {space_id} from product {product}")
    product_doc_ref = space_product_subscriptions_ref.document(product.replace("/", ""))
    product_doc_ref.update({"spaces_subscribed": firestore.ArrayRemove([space_id])})


# YOUTUBE-UPDATE: Function updated to accept and process youtube_channels
def record_product_subscription(space_id, products, categories, youtube_channels):
    try:
        subscriptions_ref = DB.collection("product_space_subscriptions")
        space_doc_ref = subscriptions_ref.document(space_id.replace("/", "_"))
        if space_doc_ref.get().exists:
            previous_doc = space_doc_ref.get().to_dict()
            previous_products = previous_doc.get("products_subscribed", [])
            previous_categories = previous_doc.get("categories_subscribed", [])
            previous_youtube = previous_doc.get("youtube_channels_subscribed", [])

            unsubscribed_products = list(set(previous_products) - set(products))
            unsubscribed_categories = list(set(previous_categories) - set(categories))
            unsubscribed_youtube = list(set(previous_youtube) - set(youtube_channels))

            with futures.ThreadPoolExecutor() as executor:
                # Unsubscribe products
                unsub_prod_futures = [executor.submit(unsubscribe_space_product, space_id, DB.collection("space_product_subscriptions"), p) for p in unsubscribed_products]
                # Unsubscribe blogs
                unsub_blog_futures = [executor.submit(unsubscribe_space_blogs, space_id, DB.collection("space_blog_subscriptions"), c) for c in unsubscribed_categories]
                # YOUTUBE-UPDATE: Unsubscribe youtube channels
                unsub_youtube_futures = [executor.submit(unsubscribe_space_youtube, space_id, DB.collection("youtube_channel_subscriptions"), y) for y in unsubscribed_youtube]
            futures.wait(unsub_prod_futures + unsub_blog_futures + unsub_youtube_futures)

        # YOUTUBE-UPDATE: Set the new list of youtube subscriptions in the document
        space_doc_ref.set({
            "products_subscribed": products,
            "categories_subscribed": categories,
            "youtube_channels_subscribed": youtube_channels
        })
    except Exception as e:
        print(f"Error recording subscription: {e}", exc_info=True)


class GoogleChatMessageConverter(MarkdownConverter):
    def convert_img(self, el, text, parent_tags): return f"<{el.attrs.get('src', '')}|{el.attrs.get('alt', '')}>"
    def convert_a(self, el, text, parent_tags): return f"<{el.get('href', '')}|{text}>"
    def convert_strong(self, el, text, parent_tags): return f"*{text}*"
    def convert_li(self, el, text, parent_tags):
        extra_padding = " " * 8
        md_list = super().convert_li(el, text, parent_tags)
        indented_bullets = [re.sub(r"^(?P<indent>\s+?)-(?P<bullet>.*?)", rf"{extra_padding}\g<indent>-\g<bullet>", line) for line in md_list.split("\n")]
        return "\n".join(indented_bullets)


def convert_html_to_chat_api_format(html):
    message = re.sub(r"^#+ (?P<header>.*?)$", r"*\g<header>*", GoogleChatMessageConverter(strong_em_symbol="_", bullets="-").convert(html), flags=re.MULTILINE)
    return re.sub(r"<(?P<link>.*?)\|`(?P<text>.*?)`>", r"<\g<link>|\g<text>>", message, flags=re.MULTILINE)


def create_message(pubsub_message):
    if "release_note" in pubsub_message:
        release_note = pubsub_message.get("release_note")
        title = f"New Release from {release_note.get('product')}"
        subtitle = release_note.get("date")
        message = convert_html_to_chat_api_format(release_note.get("html"))
        link = release_note.get("link")
    elif "blog" in pubsub_message:
        blog = pubsub_message.get("blog")
        title = f"New Blog from {blog.get('category_name')}"
        subtitle = blog.get("date")
        message = f"*{blog.get('title')}*\n\n{blog.get('summary')}"
        link = blog.get("link")
    # YOUTUBE-UPDATE: Handle the new video message type
    elif "video" in pubsub_message:
        video = pubsub_message.get("video")
        title = f"New Video from {video.get('channel_name')}"
        subtitle = video.get("date")
        # Video messages don't have a summary, so we just use the title.
        message = f"*{video.get('title')}*"
        link = video.get("link")
    else:
        title = "An Error Occurred"
        subtitle = ""
        message = "An unexpected error occurred."
        link = ""

    return Message(
        thread={"thread_key": link},
        text=f"*{title}*\n{subtitle}\n\n{message}",
        accessory_widgets=[
            {
                "button_list": {
                    "buttons": [
                        {
                            "text": "Read more",
                            "icon": {"material_icon": {"name": "link"}},
                            "on_click": {"open_link": {"url": link}},
                        }
                    ]
                }
            }
        ],
    )


def handle_pubsub_message(req: flask.Request):
    try:
        envelope = req.get_json()
        if not envelope:
            raise Exception("No Pub/Sub message received")

        pubsub_message = json.loads(base64.b64decode(envelope["message"]["data"]).decode("utf-8").strip())
        print(f"Processing Pub/Sub message: {pubsub_message}")
        space_id = pubsub_message.get("space_id")
        message = create_message(pubsub_message)

        print(f"Sending the following message to space {space_id}:\n\n{message}")
        client_utils.send_chat_message(space_id, message)
        return ("Done", 200)

    except Exception as e:
        print(f"Error handling Pub/Sub message: {e}")
        return ("Done", 200)