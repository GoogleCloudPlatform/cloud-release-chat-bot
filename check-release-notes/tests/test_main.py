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

from main import (
    remove_libraries,
)


class TestReleaseNotesFunctions:
    def test_remove_libraries_with_libraries_section_at_beginning(self):
        html = "<h3>Libraries</h3><p>Some library info</p>\n<h3>Feature</h3><p>Feature info</p>"
        html = remove_libraries(html)
        assert html == "<h3>Libraries Updated</h3>\n<h3>Feature</h3><p>Feature info</p>"

    def test_remove_libraries_with_libraries_section_at_end(self):
        html = "<h3>Feature</h3><p>Feature info</p>\n<h3>Libraries</h3><p>Some library info</p>"
        html = remove_libraries(html)
        assert html == "<h3>Feature</h3><p>Feature info</p>\n<h3>Libraries Updated</h3>"

    def test_remove_libraries_without_libraries_section(self):
        html = "<h3>Other Section</h3><p>Some other info</p>"
        html_no_change = remove_libraries(html)
        assert html_no_change == html
