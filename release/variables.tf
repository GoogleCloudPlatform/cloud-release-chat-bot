variable "project_id" {
  description = "GCP Project ID containing cloud function, and input bucket"
}

variable "cloud_functions_source_bucket_suffix" {
  description = "Suffix for GCS bucket to store Cloud Functions Source"
  default     = "cloud_release_chat_bot_source"
}

variable "client_name" {
  description = "Name for source code"
  default     = "chat-client"
}

variable "check_name" {
  description = "Name for source code"
  default     = "check-release-notes"
}

variable "blog_name" {
  description = "Name for source code"
  default     = "check-blogs"
}

variable "youtube_name" {
  description = "Name for source code"
  type        = string
  default     = "check-youtube"
}

variable "github_name" {
  description = "Name for source code"
  type        = string
  default     = "check-github"
}

variable "pub_sub_topic_name" {
  description = "Pub Sub Topic name"
  default     = "gcp-release-notes"
}

variable "region" {
  description = "GCP region in which to deploy cloud function"
  default     = "us-central1"
}

variable "runtime" {
  description = "Runtime for Cloud Run Functions"
  default     = "python312"
}
variable "timeout" {
  description = "Cloud Functions timeout in seconds"
  default     = 540
}