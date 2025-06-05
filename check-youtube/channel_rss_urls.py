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

# Description: This file contains the list of RSS URLs for each blog category.
rss_urls = [
    "https://www.youtube.com/feeds/videos.xml?channel_id=" + channel_id
    for channel_id in [
        "UCTMRxtyHoE3LPcrl-kT4AQQ", # Google Cloud
        "UCJS9pqu9BzkAMNTmzNMNhvg", # Google Cloud Tech
        "UCXYZWHSFKBpF0WUQEgEA8qA"  # Google Cloud Events
    ]
]
