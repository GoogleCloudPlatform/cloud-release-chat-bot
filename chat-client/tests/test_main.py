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

from main import convert_html_to_chat_api_format


class TestChatClientFunctions:
    def test_convert_h3_to_bold(self):
        html = convert_html_to_chat_api_format("<h3>Libraries Updated</h3>")
        assert html == "*Libraries Updated*"

    def test_convert_h3_and_p_to_bold_and_paragraph(self):
        html = convert_html_to_chat_api_format(
            "<h3>Libraries</h3><p>Some library info</p>"
        )
        assert html == "*Libraries*\n\nSome library info"

    def test_convert_h3_and_p_with_code_to_bold_and_monospace(self):
        html = convert_html_to_chat_api_format(
            "<h3>Feature</h3><p><code>This is code</code></p>"
        )
        assert html == "*Feature*\n\n`This is code`"

    def test_convert_h3_and_p_with_em_to_bold_and_italics(self):
        html = convert_html_to_chat_api_format(
            "<h3>Feature</h3><p>This is <em>italics</em>.</p>"
        )
        assert html == "*Feature*\n\nThis is _italics_."

    def test_convert_h3_and_p_with_em_and_strong_to_bold_italics_and_bold(self):
        html = convert_html_to_chat_api_format(
            "<h3>Feature</h3><p>This is <em>italics</em> and <strong>bold</strong>.</p>"
        )
        assert html == "*Feature*\n\nThis is _italics_ and *bold*."

    def test_convert_h3_and_ul_li_to_bold_and_bullet_list(self):
        html = convert_html_to_chat_api_format(
            "<h3>Feature</h3><ul><li>Item 1</li><li>Item 2</li></ul>"
        )
        assert html == "*Feature*\n\n- Item 1\n- Item 2"

    def test_convert_h3_and_nested_ul_li_to_bold_and_indented_bullet_list(self):
        html = convert_html_to_chat_api_format(
            "<h3>Feature</h3><ul><li>Item 1<ul><li>Sub Item1</li><li>Sub Item2</li></ul></li><li>Item 2</li></ul>"
        )
        assert (
            html
            == "*Feature*\n\n- Item 1\n          - Sub Item1\n          - Sub Item2\n- Item 2"
        )

    def test_convert_img_to_chat_link_format(self):
        html = convert_html_to_chat_api_format(
            '<img src="https://cloud.google.com/gemini/images/vscode-context-drawer.png" alt="Context Drawer for Gemini Code Assist for VS Code">'
        )
        assert (
            html
            == "<https://cloud.google.com/gemini/images/vscode-context-drawer.png|Context Drawer for Gemini Code Assist for VS Code>"
        )

    def test_convert_a_with_code_to_chat_link_format_simplified_text(self):
        html = '<a href="https://cloud.google.com/bigquery/docs/reference/standard-sql/load-statements"><code>LOAD DATA</code></a>'
        assert (
            convert_html_to_chat_api_format(html)
            == "<https://cloud.google.com/bigquery/docs/reference/standard-sql/load-statements|LOAD DATA>"
        )

    def test_convert_s_to_strikethrough(self):
        html = convert_html_to_chat_api_format(
            "<p>This is <s>strikethrough</s> text.</p>"
        )
        assert html == "This is ~strikethrough~ text."

    def test_convert_del_to_strikethrough(self):
        html = convert_html_to_chat_api_format(
            "<p>This is <del>strikethrough</del> text.</p>"
        )
        assert html == "This is ~strikethrough~ text."
