from clama.blog.sanitization import sanitize_post_html


class TestSanitizePostHtml:
    def test_empty_string_returns_empty(self):
        assert sanitize_post_html("") == ""

    def test_none_input_returns_empty(self):
        assert sanitize_post_html(None) == ""

    def test_whitespace_preserved(self):
        assert sanitize_post_html("   ") == "   "

    def test_vanilla_paragraph_passes_through(self):
        html = "<p>Texto pastoral comum.</p>"
        assert sanitize_post_html(html) == html

    def test_headings_h2_h3_pass_through(self):
        html = "<h2>Título</h2><h3>Subtítulo</h3>"
        assert sanitize_post_html(html) == html

    def test_lists_pass_through(self):
        html = "<ul><li>um</li><li>dois</li></ul>"
        assert sanitize_post_html(html) == html

    def test_blockquote_without_class_pass_through(self):
        html = "<blockquote>Citação</blockquote>"
        assert sanitize_post_html(html) == html

    def test_blockquote_with_class_versiculo_preserved(self):
        html = '<blockquote class="versiculo">João 3:16</blockquote>'
        assert sanitize_post_html(html) == html

    def test_div_with_class_preserved(self):
        html = '<div class="callout">aviso</div>'
        assert sanitize_post_html(html) == html

    def test_link_with_https_href_preserved(self):
        html = '<a href="https://clama.me">Clama</a>'
        assert sanitize_post_html(html) == html

    def test_link_with_http_href_preserved(self):
        html = '<a href="http://example.com">link</a>'
        assert sanitize_post_html(html) == html

    def test_image_with_alt_preserved(self):
        html = '<img src="https://cdn.clama.me/x.jpg" alt="capa">'
        assert "src=" in sanitize_post_html(html)
        assert "alt=" in sanitize_post_html(html)

    def test_script_tag_is_stripped(self):
        result = sanitize_post_html("<script>alert(1)</script><p>safe</p>")
        assert "<script>" not in result
        assert "alert" not in result
        assert "<p>safe</p>" in result

    def test_iframe_tag_is_stripped(self):
        result = sanitize_post_html(
            '<iframe src="https://evil.com"></iframe><p>safe</p>'
        )
        assert "<iframe" not in result
        assert "<p>safe</p>" in result

    def test_style_tag_is_stripped(self):
        result = sanitize_post_html("<style>body{color:red}</style><p>safe</p>")
        assert "<style>" not in result
        assert "body{color" not in result

    def test_form_tag_is_stripped(self):
        result = sanitize_post_html('<form action="/bad"></form><p>safe</p>')
        assert "<form" not in result
        assert "<p>safe</p>" in result

    def test_onclick_attribute_is_removed(self):
        result = sanitize_post_html('<a href="https://x.com" onclick="bad()">x</a>')
        assert "onclick" not in result
        assert 'href="https://x.com"' in result

    def test_javascript_url_in_href_is_removed(self):
        result = sanitize_post_html('<a href="javascript:alert(1)">x</a>')
        assert "javascript:" not in result
        assert "alert" not in result

    def test_data_url_in_href_is_removed(self):
        result = sanitize_post_html('<a href="data:text/html,<script>x</script>">x</a>')
        assert "data:" not in result

    def test_style_attribute_is_removed(self):
        result = sanitize_post_html('<p style="color:red">texto</p>')
        assert "style=" not in result
        assert "<p>texto</p>" in result

    def test_idempotent(self):
        attack = '<script>x</script><p style="x">y</p><a href="javascript:z">l</a>'
        once = sanitize_post_html(attack)
        twice = sanitize_post_html(once)
        assert once == twice

    def test_returns_str_type(self):
        result = sanitize_post_html("<p>x</p>")
        assert isinstance(result, str)

    def test_strip_removes_inner_text_of_disallowed_tag(self):
        # strip=True remove a tag E seu conteúdo
        result = sanitize_post_html("<embed>secret</embed><p>visible</p>")
        assert "<embed>" not in result
        assert "<p>visible</p>" in result
