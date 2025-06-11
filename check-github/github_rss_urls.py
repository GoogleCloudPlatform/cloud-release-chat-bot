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

# Description: This file contains the list of RSS URLs for Github repos.
github_owner_map = [
    {
        "owner": "GoogleCloudPlatform",
        "repos": [
            "professional-services-data-validator",
            "spanner-migration-tool",
        ],
    },
    {"owner": "google", "repos": ["adk-python"]},
    {"owner": "apache", "repos": ["airflow", "beam", "iceberg", "spark"]},
]

rss_urls = []

for owner_map in github_owner_map:
    for repo in owner_map.get("repos"):
        url = f"https://www.github.com/{owner_map.get('owner')}/{repo}/releases.atom"
        rss_urls.append(url)
