# Google Cloud Release Notes Chat Bot 

This project implements a chat bot that delivers Google Cloud release notes to users via a chat interface.  It leverages four Cloud Run functions, Pub/Sub, and Firestore for a scalable and efficient architecture.

![ui](/images/ui.png)

## Overview

The bot operates using the following main components:

1.  **Release Notes Checker Function:** This function is scheduled to run every 30 minutes. It fetches the latest Google Cloud release notes, identifies any new or updated notes, and publishes them as messages to a Pub/Sub topic.

2.  **Blogs Checker Function:** This function is scheduled to run every 30 minutes. It fetches the latest Google Cloud blogs, identifies any new blogs, and publishes them as messages to a Pub/Sub topic.

3.  **Youtube Checker Function:** This function is scheduled to run every 30 minutes. It fetches the latest Google Cloud videos, identifies any new videos, and publishes them as messages to a Pub/Sub topic.

4.  **Chat Client Function:** This function subscribes to the Pub/Sub topic.  When a new release note message arrives, it processes the message, retrieves relevant space subscriptions from Firestore, and sends the release note notification to the appropriate chat spaces.  Space subscriptions (i.e., which spaces want to receive notifications for which Google Cloud products/services) are stored in Firestore.

## Architecture

![chat](/images/arch.png)


## Firestore Database

The bot uses Firestore to manage space subscriptions and store the latest release notes.  The follwing collections are used in the following pattern:

1.  **`cloud_release_notes`:** This collection stores the latest release notes fetched by the `release-notes-checker` function.  Each document in this collection represents a single release note and contain fields like `html`, `release_date`.

2.  **`product_space_subscriptions`:** This collection stores the relationship between chat spaces and the Google Cloud products/blogs/videos they've subscribed to.  Each document in this collection represents a chat space.  Within each space document, there's an array field (e.g., `products`, `categories`) that contains the names of the products/blogs that the space has subscribed to. This enables efficient retrieval of the products a given space is interested in.  Example:

    ```json
    {
      "space": "space123",
      "products": ["Compute Engine", "Cloud Storage"],
      "categories": ["Data & Analytics", ...],
      "youtube_channels_subscribed": ["Google Cloud Tech", ...]
    }
    ```

3.  **`space_product_subscriptions`:** This collection stores the relationship between Google Cloud products/services and the chat spaces that are subscribed to them.  Each document in this collection represents a product (e.g., "Compute Engine", "Cloud Storage").  Within each product document, there's an array field (e.g., `spaces`) that contains the IDs of the chat spaces that have subscribed to that product.  This allows for efficient retrieval of spaces interested in a particular product's release notes.  Example:

    ```json
    {
      "product": "Compute Engine",
      "spaces": ["space123", "space456", "space789"]
    }
    ```

A similar pattern is used for both blogs and Youtube videos


## Deployment

See the deployment steps in the release [README](/release/README.md)