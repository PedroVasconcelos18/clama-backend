from clama.blog.tiptap_converter import tiptap_json_to_html


def _doc(*nodes):
    return {"type": "doc", "content": list(nodes)}


def _text(text, *marks):
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


class TestTiptapJsonToHtml:
    def test_empty_input_returns_empty(self):
        assert tiptap_json_to_html(None) == ""
        assert tiptap_json_to_html({}) == ""

    def test_invalid_input_returns_empty(self):
        assert tiptap_json_to_html("string") == ""
        assert tiptap_json_to_html(42) == ""

    def test_simple_paragraph(self):
        doc = _doc({"type": "paragraph", "content": [_text("Olá mundo")]})
        assert tiptap_json_to_html(doc) == "<p>Olá mundo</p>"

    def test_paragraph_with_bold(self):
        doc = _doc(
            {
                "type": "paragraph",
                "content": [_text("Olá ", {"type": "bold"}), _text("mundo")],
            }
        )
        assert tiptap_json_to_html(doc) == "<p><strong>Olá </strong>mundo</p>"

    def test_paragraph_with_italic(self):
        doc = _doc(
            {"type": "paragraph", "content": [_text("texto", {"type": "italic"})]}
        )
        assert tiptap_json_to_html(doc) == "<p><em>texto</em></p>"

    def test_paragraph_with_link(self):
        doc = _doc(
            {
                "type": "paragraph",
                "content": [
                    _text(
                        "clama",
                        {"type": "link", "attrs": {"href": "https://clama.me"}},
                    )
                ],
            }
        )
        assert (
            tiptap_json_to_html(doc) == '<p><a href="https://clama.me">clama</a></p>'
        )

    def test_combined_marks_bold_italic_link(self):
        doc = _doc(
            {
                "type": "paragraph",
                "content": [
                    _text(
                        "x",
                        {"type": "bold"},
                        {"type": "italic"},
                        {"type": "link", "attrs": {"href": "https://x.com"}},
                    )
                ],
            }
        )
        # marks aplicadas in-order: bold > italic > link
        assert (
            tiptap_json_to_html(doc)
            == '<p><a href="https://x.com"><em><strong>x</strong></em></a></p>'
        )

    def test_heading_level_2(self):
        doc = _doc(
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [_text("Título")],
            }
        )
        assert tiptap_json_to_html(doc) == "<h2>Título</h2>"

    def test_heading_level_3(self):
        doc = _doc(
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [_text("Sub")],
            }
        )
        assert tiptap_json_to_html(doc) == "<h3>Sub</h3>"

    def test_heading_invalid_level_falls_back_to_paragraph(self):
        doc = _doc(
            {
                "type": "heading",
                "attrs": {"level": 5},
                "content": [_text("nope")],
            }
        )
        assert tiptap_json_to_html(doc) == "<p>nope</p>"

    def test_bullet_list(self):
        doc = _doc(
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [_text("um")],
                            }
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [_text("dois")],
                            }
                        ],
                    },
                ],
            }
        )
        assert (
            tiptap_json_to_html(doc)
            == "<ul><li><p>um</p></li><li><p>dois</p></li></ul>"
        )

    def test_ordered_list(self):
        doc = _doc(
            {
                "type": "orderedList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [_text("x")]}
                        ],
                    }
                ],
            }
        )
        assert tiptap_json_to_html(doc) == "<ol><li><p>x</p></li></ol>"

    def test_blockquote(self):
        doc = _doc(
            {
                "type": "blockquote",
                "content": [
                    {"type": "paragraph", "content": [_text("citação")]}
                ],
            }
        )
        assert tiptap_json_to_html(doc) == "<blockquote><p>citação</p></blockquote>"

    def test_horizontal_rule(self):
        doc = _doc({"type": "horizontalRule"})
        assert tiptap_json_to_html(doc) == "<hr>"

    def test_hard_break(self):
        doc = _doc(
            {"type": "paragraph", "content": [_text("a"), {"type": "hardBreak"}, _text("b")]}
        )
        assert tiptap_json_to_html(doc) == "<p>a<br>b</p>"

    def test_image_with_src_and_alt(self):
        doc = _doc({"type": "image", "attrs": {"src": "https://x/y.jpg", "alt": "capa"}})
        assert tiptap_json_to_html(doc) == '<img src="https://x/y.jpg" alt="capa">'

    def test_image_without_src_returns_empty(self):
        doc = _doc({"type": "image", "attrs": {"alt": "no src"}})
        assert tiptap_json_to_html(doc) == ""

    def test_text_is_html_escaped(self):
        doc = _doc(
            {"type": "paragraph", "content": [_text("<script>x</script>")]}
        )
        assert (
            tiptap_json_to_html(doc) == "<p>&lt;script&gt;x&lt;/script&gt;</p>"
        )

    def test_ampersand_is_escaped(self):
        doc = _doc({"type": "paragraph", "content": [_text("A & B")]})
        assert tiptap_json_to_html(doc) == "<p>A &amp; B</p>"

    def test_unknown_node_type_returns_empty(self):
        doc = _doc({"type": "frobnicate", "content": [_text("ignored")]})
        assert tiptap_json_to_html(doc) == ""

    def test_empty_doc_returns_empty(self):
        doc = _doc()
        assert tiptap_json_to_html(doc) == ""

    def test_link_href_is_escaped(self):
        doc = _doc(
            {
                "type": "paragraph",
                "content": [
                    _text(
                        "x",
                        {
                            "type": "link",
                            "attrs": {"href": 'https://x.com?"a"=1'},
                        },
                    )
                ],
            }
        )
        result = tiptap_json_to_html(doc)
        assert "&quot;" in result
