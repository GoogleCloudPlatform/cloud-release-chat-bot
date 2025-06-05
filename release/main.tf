terraform {
  backend "gcs" {
    prefix  = "terraform/state"
    project = "gcp-release-notes-bot-test"
  }
}
# Zip up source code folder
data "google_project" "project" {
  project_id = var.project_id
}

resource "google_project_service" "project_services" {
  for_each = toset([
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "firestore.googleapis.com",
    "logging.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudfunctions.googleapis.com",
    "run.googleapis.com",
    "pubsub.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
    "chat.googleapis.com",
    "gsuiteaddons.googleapis.com",
    "appsmarket-component.googleapis.com",
    "aiplatform.googleapis.com"
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false # Keep APIs enabled after apply
}

output "project_number" {
  value = data.google_project.project.number
}

resource "google_storage_bucket" "bucket" {
  name          = "${var.project_id}-${var.cloud_functions_source_bucket_suffix}"
  project       = var.project_id
  location      = var.region
  force_destroy = true
}

data "archive_file" "function_source_check" {
  type        = "zip"
  output_path = format("%s.zip", var.check_name)
  source_dir  = format(".././%s/", var.check_name)
}

data "archive_file" "function_source_blog" {
  type        = "zip"
  output_path = format("%s.zip", var.blog_name)
  source_dir  = format(".././%s/", var.blog_name)
}

data "archive_file" "function_source_youtube" {
  type        = "zip"
  output_path = format("%s.zip", var.youtube_name)
  source_dir  = format(".././%s/", var.youtube_name)
}


data "archive_file" "function_source_client" {
  type        = "zip"
  output_path = format("%s.zip", var.client_name)
  source_dir  = format(".././%s/", var.client_name)
}

resource "google_storage_bucket_object" "function_zip_object_check" {
  depends_on   = [google_storage_bucket.bucket]
  name         = "cloudfunctions_source/${data.archive_file.function_source_check.output_md5}-${basename(data.archive_file.function_source_check.output_path)}"
  bucket       = google_storage_bucket.bucket.name
  source       = data.archive_file.function_source_check.output_path
  content_type = "application/zip"
}

resource "google_storage_bucket_object" "function_zip_object_blog" {
  depends_on   = [google_storage_bucket.bucket]
  name         = "cloudfunctions_source/${data.archive_file.function_source_blog.output_md5}-${basename(data.archive_file.function_source_blog.output_path)}"
  bucket       = google_storage_bucket.bucket.name
  source       = data.archive_file.function_source_blog.output_path
  content_type = "application/zip"
}

resource "google_storage_bucket_object" "function_zip_object_youtube" {
  depends_on   = [google_storage_bucket.bucket]
  name         = "cloudfunctions_source/${data.archive_file.function_source_youtube.output_md5}-${basename(data.archive_file.function_source_youtube.output_path)}"
  bucket       = google_storage_bucket.bucket.name
  source       = data.archive_file.function_source_youtube.output_path
  content_type = "application/zip"
}

resource "google_storage_bucket_object" "function_zip_object_client" {
  depends_on   = [google_storage_bucket.bucket]
  name         = "cloudfunctions_source/${data.archive_file.function_source_client.output_md5}-${basename(data.archive_file.function_source_client.output_path)}"
  bucket       = google_storage_bucket.bucket.name
  source       = data.archive_file.function_source_client.output_path
  content_type = "application/zip"
}

resource "google_cloudfunctions2_function" "check_function" {
  depends_on = [google_storage_bucket_object.function_zip_object_check]
  location   = var.region
  name       = var.check_name
  project    = var.project_id
  build_config {
    runtime     = var.runtime
    entry_point = "http_request"
    source {
      storage_source {
        bucket = google_storage_bucket.bucket.name
        object = google_storage_bucket_object.function_zip_object_check.name
      }
    }
  }
  service_config {
    max_instance_count = 1
    available_memory   = "4Gi"
    available_cpu      = "8"
    timeout_seconds    = var.timeout
    environment_variables = {
      GCP_PROJECT_ID     = var.project_id
      PUB_SUB_TOPIC_NAME = var.pub_sub_topic_name
    }
  }
}

resource "google_cloudfunctions2_function" "blog_function" {
  depends_on = [google_storage_bucket_object.function_zip_object_blog]
  location   = var.region
  name       = var.blog_name
  project    = var.project_id
  build_config {
    runtime     = var.runtime
    entry_point = "http_request"
    source {
      storage_source {
        bucket = google_storage_bucket.bucket.name
        object = google_storage_bucket_object.function_zip_object_blog.name
      }
    }
  }
  service_config {
    max_instance_count = 1
    available_memory   = "4Gi"
    available_cpu      = "8"
    timeout_seconds    = var.timeout
    environment_variables = {
      GCP_PROJECT_ID     = var.project_id
      PUB_SUB_TOPIC_NAME = var.pub_sub_topic_name
    }
  }
}

resource "google_cloudfunctions2_function" "youtube_video_function" {
  depends_on = [google_storage_bucket_object.function_zip_object_youtube]
  location   = var.region
  name       = var.youtube_name
  project    = var.project_id
  build_config {
    runtime     = var.runtime
    entry_point = "http_request"
    source {
      storage_source {
        bucket = google_storage_bucket.bucket.name
        object = google_storage_bucket_object.function_zip_object_youtube.name
      }
    }
  }
  service_config {
    max_instance_count = 1
    available_memory   = "4Gi"
    available_cpu      = "8"
    timeout_seconds    = var.timeout
    environment_variables = {
      GCP_PROJECT_ID     = var.project_id
      PUB_SUB_TOPIC_NAME = var.pub_sub_topic_name
    }
  }
}

resource "google_cloudfunctions2_function" "client_function" {
  depends_on = [google_storage_bucket_object.function_zip_object_client]
  location   = var.region
  name       = var.client_name
  project    = var.project_id
  build_config {
    runtime     = var.runtime
    entry_point = "chat_app"
    source {
      storage_source {
        bucket = google_storage_bucket.bucket.name
        object = google_storage_bucket_object.function_zip_object_client.name
      }
    }
  }
  service_config {
    min_instance_count = 1
    available_memory   = "4Gi"
    available_cpu      = "8"
    timeout_seconds    = var.timeout
    environment_variables = {
      BASE_URL       = "https://${var.region}-${var.project_id}.cloudfunctions.net/${var.client_name}"
      GCP_PROJECT_ID = var.project_id
    }
  }
}

resource "google_service_account" "service_account" {
  account_id   = "cloud-run-pubsub-invoker"
  display_name = "Cloud Run Pub/Sub Invoker"
  project      = var.project_id
}

# Grant Cloud Run Invoker role on the client Cloud Run function
resource "google_cloud_run_service_iam_binding" "cloud_run_service_agent_client" {
  depends_on = [google_service_account.service_account]
  project    = var.project_id
  location   = var.region
  service    = google_cloudfunctions2_function.client_function.name
  role       = "roles/run.invoker"
  members    = ["serviceAccount:${google_service_account.service_account.email}", "serviceAccount:service-${data.google_project.project.number}@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"]
}

# Grant Cloud Run Invoker role on the check Cloud Run function
resource "google_cloud_run_service_iam_binding" "cloud_run_service_agent_check" {
  depends_on = [google_service_account.service_account]
  project    = var.project_id
  location   = var.region
  service    = google_cloudfunctions2_function.check_function.name
  role       = "roles/run.invoker"
  members    = ["serviceAccount:${google_service_account.service_account.email}"]
}

# Grant Cloud Run Invoker role on the blog Cloud Run function
resource "google_cloud_run_service_iam_binding" "cloud_run_service_agent_blog" {
  depends_on = [google_service_account.service_account]
  project    = var.project_id
  location   = var.region
  service    = google_cloudfunctions2_function.blog_function.name
  role       = "roles/run.invoker"
  members    = ["serviceAccount:${google_service_account.service_account.email}"]
}

# Grant Cloud Run Invoker role on the YouTube video Cloud Run function
resource "google_cloud_run_service_iam_binding" "cloud_run_service_agent_youtube" {
  depends_on = [google_service_account.service_account]
  project    = var.project_id
  location   = var.region
  service    = google_cloudfunctions2_function.youtube_video_function.name
  role       = "roles/run.invoker"
  members    = ["serviceAccount:${google_service_account.service_account.email}"]
}

resource "google_project_iam_member" "service_account_token_creator_binding" {
  project = var.project_id
  member  = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
  role    = "roles/iam.serviceAccountTokenCreator"
}

resource "google_pubsub_topic" "topic" {
  name    = var.pub_sub_topic_name
  project = var.project_id
}

resource "google_pubsub_subscription" "subscription" {
  depends_on           = [google_pubsub_topic.topic, google_cloudfunctions2_function.client_function]
  project              = var.project_id
  name                 = "myRunSubscription"
  topic                = google_pubsub_topic.topic.id
  ack_deadline_seconds = 600
  push_config {
    push_endpoint = "${google_cloudfunctions2_function.client_function.url}/messages"
    oidc_token {
      service_account_email = google_service_account.service_account.email
      audience              = google_cloudfunctions2_function.client_function.url
    }
  }
}

resource "google_cloud_scheduler_job" "job" {
  name             = "refresh-release-notes"
  project          = var.project_id
  region           = var.region
  description      = "Refresh releases notes every 5 minutes"
  schedule         = "*/5 * * * *"
  time_zone        = "America/New_York"
  attempt_deadline = "240s" # 4 minutes

  http_target {
    http_method = "GET"
    uri         = google_cloudfunctions2_function.check_function.url

    oidc_token {
      audience              = google_cloudfunctions2_function.check_function.url
      service_account_email = google_service_account.service_account.email
    }
  }
}

resource "google_cloud_scheduler_job" "blog_job" {
  name             = "refresh-blogs"
  project          = var.project_id
  region           = var.region
  description      = "Refresh blogs every 30 minutes"
  schedule         = "*/30 * * * *"
  time_zone        = "America/New_York"
  attempt_deadline = "320s"

  http_target {
    http_method = "GET"
    uri         = google_cloudfunctions2_function.blog_function.url

    oidc_token {
      audience              = google_cloudfunctions2_function.blog_function.url
      service_account_email = google_service_account.service_account.email
    }
  }
}

# Schedule the YouTube video function to run periodically
resource "google_cloud_scheduler_job" "youtube_video_job" {
  name             = "refresh-youtube-videos"
  project          = var.project_id
  region           = var.region
  description      = "Refresh YouTube videos every hour"
  schedule         = "0 * * * *" # Runs at the top of every hour
  time_zone        = "America/New_York"
  attempt_deadline = "320s"

  http_target {
    http_method = "GET"
    uri         = google_cloudfunctions2_function.youtube_video_function.url

    oidc_token {
      audience              = google_cloudfunctions2_function.youtube_video_function.url
      service_account_email = google_service_account.service_account.email
    }
  }
}

resource "google_firestore_database" "database" {
  depends_on              = [google_project_service.project_services]
  project                 = var.project_id
  name                    = "(default)"
  location_id             = "nam5"
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"
}