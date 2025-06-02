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
                products = products_doc.to_dict().get("products_subscribed", [])
                categories = products_doc.to_dict().get("categories_subscribed", [])
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
                futures.wait(
                    unsubscribe_space_product_futures + unsubscribe_space_blogs_futures
                )
                product_doc_ref.delete()
                print(
                    f"Unsubscribed space {space_id} from all products and categories."
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
                print(f"Submitting dialog: {submitDialog(req_json)}")
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
    "All Data Blogs": getattr(
        client_utils, "data_categories", []
    ),  # Use getattr for safety
    # "All AI Blogs": client_utils.ai_blogs_categories, # Example
}


def _get_expanded_subscription_set(subscribed_items, category_map):
    initial_set = set(subscribed_items)
    expanded_set = set(initial_set)  # Start with explicit items

    for category_tag, category_list in category_map.items():
        if category_tag in initial_set:
            # If the user subscribed to a category tag, add all items from that category
            expanded_set.update(category_list)

    return expanded_set


# Helper function to get members excluding the tag itself
def get_members_only(category_tag, category_map):
    """Gets items in a category, excluding the category tag itself."""
    full_list = category_map.get(category_tag, [])
    # Using str() ensures comparison works if lists somehow contain non-strings
    # This filters out the tag itself from the list of members.
    return {str(item) for item in full_list if str(item) != str(category_tag)}


def openInitialDialog(request_json):
    """
    Opens the initial subscription dialog. If a category tag (e.g., "All App Mod Products")
    is present in the saved subscriptions (which also includes individual members),
    only the category tag itself is marked selected in the UI, suppressing the selection
    of the individual members of that category (even if they are in the saved list).
    Other explicitly saved items remain selected.
    Handles overrides ("All Products", "All Blogs").
    """
    try:
        # Default empty sets
        products_subscribed_set = set()
        categories_subscribed_set = set()
        doc_exists = False

        # Fetch subscriptions
        space_name = request_json["chat"]["appCommandPayload"]["space"]["name"].replace(
            "/", "_"
        )
        subscriptions_ref = DB.collection("product_space_subscriptions")
        product_doc_ref = subscriptions_ref.document(space_name)
        products_doc = product_doc_ref.get()
        doc_exists = products_doc.exists

        if doc_exists:
            doc_data = products_doc.to_dict()
            products_subscribed_set = set(doc_data.get("products_subscribed", []))
            categories_subscribed_set = set(doc_data.get("categories_subscribed", []))

        # --- Determine Overrides ---
        all_products_override = "All Products" in products_subscribed_set
        all_blogs_override = "All Blogs" in categories_subscribed_set

        # --- Generate Product Dialog Items ---
        notes = []
        all_possible_products = getattr(client_utils, "google_cloud_products", [])

        if all_products_override:
            # Handle global override - only "All Products" is selected
            for product in all_possible_products:
                is_selected = product == "All Products"
                notes.append(
                    {"text": product, "value": product, "selected": is_selected}
                )
        elif doc_exists:
            # Identify active category tags and the individual products they cover
            active_product_tags = {
                tag for tag in CATEGORY_MAP if tag in products_subscribed_set
            }
            products_covered_by_active_tags = set()
            if active_product_tags:
                for tag in active_product_tags:
                    # Get members ONLY (exclude the tag)
                    products_covered_by_active_tags.update(
                        get_members_only(tag, CATEGORY_MAP)
                    )

            # Determine selection state for each possible product
            for product in all_possible_products:
                is_selected = False  # Default
                # Rule 1: Is it an active category tag?
                if product in active_product_tags:
                    is_selected = True
                # Rule 2: Is it in the subscribed list AND NOT covered by an active tag?
                elif (
                    product in products_subscribed_set
                    and product not in products_covered_by_active_tags
                ):
                    is_selected = True

                notes.append(
                    {"text": product, "value": product, "selected": is_selected}
                )
        else:
            # No document exists and no override, nothing is selected
            for product in all_possible_products:
                notes.append({"text": product, "value": product, "selected": False})

        # --- Generate Blog Dialog Items (Similar Logic) ---
        blogs = []
        all_possible_categories = getattr(client_utils, "categories", [])

        if all_blogs_override:
            # Handle global override - only "All Blogs" is selected
            for category in all_possible_categories:
                is_selected = category == "All Blogs"
                blogs.append(
                    {"text": category, "value": category, "selected": is_selected}
                )
        elif doc_exists:
            # Identify active category tags and the individual blogs they cover
            active_blog_tags = {
                tag for tag in BLOG_CATEGORY_MAP if tag in categories_subscribed_set
            }
            blogs_covered_by_active_tags = set()
            if active_blog_tags:
                for tag in active_blog_tags:
                    # Get members ONLY (exclude the tag)
                    blogs_covered_by_active_tags.update(
                        get_members_only(tag, BLOG_CATEGORY_MAP)
                    )

            # Determine selection state for each possible category
            for category in all_possible_categories:
                is_selected = False  # Default
                # Rule 1: Is it an active category tag?
                if category in active_blog_tags:
                    is_selected = True
                # Rule 2: Is it in the subscribed list AND NOT covered by an active tag?
                elif (
                    category in categories_subscribed_set
                    and category not in blogs_covered_by_active_tags
                ):
                    is_selected = True

                blogs.append(
                    {"text": category, "value": category, "selected": is_selected}
                )
        else:
            # No document exists and no override, nothing is selected
            for category in all_possible_categories:
                blogs.append({"text": category, "value": category, "selected": False})

        return client_utils.retrieve_dialog_response(notes, blogs)

    except Exception as e:
        # Add proper error handling/logging
        space_name_for_error = "unknown"
        try:
            # Attempt to get space name for logging, but don't fail if request structure is unexpected
            space_name_for_error = (
                request_json.get("chat", {})
                .get("appCommandPayload", {})
                .get("space", {})
                .get("name", "unknown")
                .replace("/", "_")
            )
        except Exception:
            pass  # Ignore errors just trying to get the name for logging
        print(f"Error opening initial dialog for space {space_name_for_error}: {e}")
        # Return an error response or a default dialog
        notes = [
            {"text": p, "value": p, "selected": False}
            for p in getattr(client_utils, "google_cloud_products", [])
        ]
        blogs = [
            {"text": c, "value": c, "selected": False}
            for c in getattr(client_utils, "categories", [])
        ]
        return client_utils.retrieve_dialog_response(
            notes, blogs, error="Failed to load subscriptions."
        )


def returnSubscriptions(request_json):
    subscriptions_ref = DB.collection("product_space_subscriptions")
    product_doc_ref = subscriptions_ref.document(
        request_json["chat"]["appCommandPayload"]["space"]["name"].replace("/", "_")
    )
    products_doc = product_doc_ref.get()
    notes = []
    blogs = []
    if products_doc.exists:
        products = products_doc.to_dict().get("products_subscribed", [])
        categories = products_doc.to_dict().get("categories_subscribed", [])
        product_list = (
            "\n".join(f"- {product}" for product in products) if products else "None"
        )
        category_list = (
            "\n".join(f"- {category}" for category in categories)
            if categories
            else "None"
        )

        message_text = f"Current Subscriptions for this Space:\n\nProducts:\n{product_list}\n\nBlog categories:\n{category_list}"

        return {
            "hostAppDataAction": {
                "chatDataAction": {
                    "createMessageAction": {
                        "message": {
                            "text": message_text,
                        }
                    }
                }
            }
        }
    else:
        return {
            "hostAppDataAction": {
                "chatDataAction": {
                    "createMessageAction": {
                        "message": {
                            "text": "There are no subscriptions for this space yet. Use `/subscribe` to add some!",
                        }
                    }
                }
            }
        }


def handle_templatized_notes_inputs(products):
    initial_products_set = set(products)

    all_products_flag = "All Products" in initial_products_set

    if all_products_flag:
        final_products_set = set(client_utils.google_cloud_products)
        return sorted(list(final_products_set)), True

    final_products_set = set(initial_products_set)

    for category_tag, category_product_list in CATEGORY_MAP.items():
        if category_tag in initial_products_set:
            final_products_set.update(category_product_list)
    return sorted(list(final_products_set)), False


def handle_templatized_blogs_inputs(categories):
    all_blogs = "All Blogs" in categories
    all_data_blogs = "All Data Blogs" in categories
    if all_data_blogs and not all_blogs:
        categories.extend(client_utils.data_categories)
    if all_blogs:
        categories = client_utils.categories
    categories = list(set(categories))
    return categories, all_blogs


def submitDialog(event):
    chatUser = event["chat"]["user"]
    products = []
    categories = []
    all_products = False
    all_blogs = False
    space_id = event["chat"]["buttonClickedPayload"]["space"]["name"]
    if "formInputs" in event["commonEventObject"]:
        if "contactType" in event["commonEventObject"]["formInputs"]:
            products = event["commonEventObject"]["formInputs"]["contactType"][
                "stringInputs"
            ]["value"]
            products, all_products = handle_templatized_notes_inputs(products)
        if "blogType" in event["commonEventObject"]["formInputs"]:
            categories = event["commonEventObject"]["formInputs"]["blogType"][
                "stringInputs"
            ]["value"]
            categories, all_blogs = handle_templatized_blogs_inputs(categories)
    with futures.ThreadPoolExecutor() as executor:
        record_space_subscription_futures = [
            executor.submit(record_space_subscription, space_id, product)
            for product in products
        ]
        record_space_blogs_futures = [
            executor.submit(record_space_blogs, space_id, category)
            for category in categories
        ]
    futures.wait(record_space_subscription_futures + record_space_blogs_futures)
    record_product_subscription(space_id, products, categories)

    response = ""
    if products:  # More concise way to check if list is not empty
        product_message = f"products: {', '.join(products)}"
    else:
        product_message = "no products"  # Or a more appropriate message

    if all_products:
        product_message = "All Products"

    if categories:
        category_message = f"and categories: {', '.join(categories)}"
    else:
        category_message = "and no categories"

    if all_blogs:
        category_message = "and All Categories"

    if products or categories:  # Check if either products or categories are selected
        response = f"😄🎉 Your request has been successfully submitted!\n\nThis space is now subscribed to {product_message} {category_message}."
    else:
        response = "😄🎉 Your request has been successfully submitted!\n\nThis space is now unsubscribed from any products or categories."

    return {
        "hostAppDataAction": {
            "chatDataAction": {
                "createMessageAction": {
                    "message": {"privateMessageViewer": chatUser, "text": response}
                }
            }
        }
    }


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
            category_doc_ref.set(
                {"category": category, "spaces_subscribed": [space_id]}
            )

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


def unsubscribe_space_blogs(space_id, space_blog_subscriptions_ref, category):
    print(f"Unsubscribing space {space_id} from category {category}")
    categories_doc_ref = space_blog_subscriptions_ref.document(category)
    categories_doc_ref.update({"spaces_subscribed": firestore.ArrayRemove([space_id])})


def unsubscribe_space_product(space_id, space_product_subscriptions_ref, product):
    print(f"Unsubscribing space {space_id} from product {product}")
    product_doc_ref = space_product_subscriptions_ref.document(product.replace("/", ""))
    product_doc_ref.update({"spaces_subscribed": firestore.ArrayRemove([space_id])})


def record_product_subscription(space_id, products, categories):
    try:
        subscriptions_ref = DB.collection("product_space_subscriptions")
        space_doc_ref = subscriptions_ref.document(space_id.replace("/", "_"))
        if space_doc_ref.get().exists:
            previous_products = (
                space_doc_ref.get().to_dict().get("products_subscribed", [])
            )
            previous_categories = (
                space_doc_ref.get().to_dict().get("categories_subscribed", [])
            )
            if (len(previous_products) > len(products)) or (
                len(previous_categories) > len(categories)
            ):
                unsubscribed_products = list(set(previous_products) - set(products))
                unsubscribed_categories = list(
                    set(previous_categories) - set(categories)
                )
                with futures.ThreadPoolExecutor() as executor:
                    unsubscribe_space_product_futures = [
                        executor.submit(
                            unsubscribe_space_product,
                            space_id,
                            DB.collection("space_product_subscriptions"),
                            product,
                        )
                        for product in unsubscribed_products
                    ]
                    unsubscribe_space_blogs_futures = [
                        executor.submit(
                            unsubscribe_space_blogs,
                            space_id,
                            DB.collection("space_blog_subscriptions"),
                            category,
                        )
                        for category in unsubscribed_categories
                    ]
                futures.wait(
                    unsubscribe_space_product_futures + unsubscribe_space_blogs_futures
                )
        space_doc_ref.set(
            {"products_subscribed": products, "categories_subscribed": categories}
        )
    except Exception as e:
        print(f"Error recording subscription: {e}", exc_info=True)


class GoogleChatMessageConverter(MarkdownConverter):
    """Custom Markdown converter for Google Chat API formatting."""

    # Convert HTML images to a Google Chat API formatted hyperlink to the image
    def convert_img(self, el, text, parent_tags):
        alt = el.attrs.get("alt", None) or ""
        src = el.attrs.get("src", None) or ""
        return f"<{src}|{alt}>"

    # Convert hyperlinks to Google Chat API format
    def convert_a(self, el, text, parent_tags):
        return f"<{el.get('href', '')}|{text}>"

    def convert_strong(self, el, text, parent_tags):
        # Convert bold text to Chat API format
        return f"*{text}*"

    def convert_li(self, el, text, parent_tags):
        # Add 8 more indentation spaces for nested bullets
        extra_padding = " " * 8
        md_list = super().convert_li(el, text, parent_tags)
        indented_bullets = []
        for line in md_list.split("\n"):
            indented_bullets.append(
                re.sub(
                    r"^(?P<indent>\s+?)-(?P<bullet>.*?)",
                    rf"{extra_padding}\g<indent>-\g<bullet>",
                    line,
                )
            )
        return "\n".join(indented_bullets)


# Convert HTML to Google Chat API formatted message
def convert_html_to_chat_api_format(html):
    # Handle converting headers explicitly before returning because
    # MarkdownConverter does not support overriding the convert_hN method.
    return re.sub(
        r"^#+ (?P<header>.*?)$",
        r"*\g<header>*",
        GoogleChatMessageConverter(strong_em_symbol="_", bullets="-").convert(html),
        flags=re.MULTILINE,
    )


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
    else:
        title = "An Error Occurred"
        subtitle = ""
        message = f"An unexpected error occurred."
        link = ""

    return Message(
        thread={"thread_key": link},
        text=f"{title}\n{subtitle}\n\n{message}",
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

        pubsub_message = json.loads(
            base64.b64decode(envelope["message"]["data"]).decode("utf-8").strip()
        )
        print(f"Processing Pub/Sub message: {pubsub_message}")
        space_id = pubsub_message.get("space_id")
        message = create_message(pubsub_message)

        print(f"Sending the following message to space {space_id}:\n\n{message}")
        client_utils.send_chat_message(space_id, message)
        return ("Done", 200)

    except Exception as e:
        # Return a 200 to acknowledge receipt of the message
        # otherwise Pub/Sub will continue to trigger this function
        print(f"Error handling Pub/Sub message: {e}")
        return ("Done", 200)
