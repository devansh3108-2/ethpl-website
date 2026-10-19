from app import render_markdown


def test_markdown_escapes_active_html_and_dangerous_urls():
    rendered = render_markdown(
        '# Heading\n<script>alert(1)</script>\n'
        '<img src=x onerror="alert(2)">\n'
        '<a href="javascript:alert(3)">bad</a>'
    )
    assert "<script" not in rendered
    assert "<img" not in rendered
    assert "<a " not in rendered
    assert "<img" not in rendered
    assert 'href="javascript:' not in rendered
    assert "&lt;script&gt;" in rendered


def test_supported_markdown_formatting_is_preserved():
    rendered = render_markdown(
        "# Heading\n**bold** and *emphasis*\n- first\n- second\n\n> quotation"
    )
    assert "<h1>Heading</h1>" in rendered
    assert "<strong>bold</strong>" in rendered
    assert "<em>emphasis</em>" in rendered
    assert "<ul>" in rendered and "<li>first</li>" in rendered
    assert "<blockquote>quotation</blockquote>" in rendered


def test_malformed_markup_remains_inert():
    rendered = render_markdown("**bold <svg/onload=alert(1)>**")
    assert "<svg" not in rendered
    assert "&lt;svg/onload=alert(1)&gt;" in rendered
