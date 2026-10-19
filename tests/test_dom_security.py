"""DOM-safety guards for the JavaScript that ships to visitors.

Phase 3 removed demo-sync.js and admin.js, so the tests that pinned their
internals are gone with them. The property those tests protected still matters
and is now asserted across every script rather than for two files: no code
that reaches a visitor may build DOM from an interpolated markup string.

That is a stronger guarantee than before. The old suite checked two named
files; this checks whatever is in static/js, including anything added later.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "static" / "js"

HTML_PARSING_SINKS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")


def strip_js_comments(source: str) -> str:
    """Drop // and /* */ comments so sink checks scan code, not prose.

    Naive on purpose: it does not understand string or regex literals. That is
    fine for the files it guards, and it exists so a comment *documenting* that
    innerHTML is unused cannot itself fail the check.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def shipped_scripts():
    return sorted(JS_DIR.glob("*.js"))


def test_there_is_javascript_to_check():
    """Guards the guard: a glob that matches nothing would pass silently."""
    assert shipped_scripts(), "no scripts found in static/js"


def test_no_shipped_script_reaches_an_html_parsing_sink():
    """Stored content must reach the page as text, never as parsed markup.

    Destination copy, service descriptions and testimonials are editable in
    Strapi by someone who is not a developer. If any of that reached an HTML
    sink, a stray angle bracket would break the page and a deliberate payload
    would be a stored-XSS vector.
    """
    for path in shipped_scripts():
        code = strip_js_comments(path.read_text(encoding="utf-8"))
        for sink in HTML_PARSING_SINKS:
            assert sink not in code, f"{path.name} must never assign via {sink}"


def test_feedback_and_toasts_use_text_content():
    code = (JS_DIR / "app.js").read_text(encoding="utf-8")
    assert "feedback.textContent = \'\'" in code


def test_removed_demo_scripts_are_really_gone():
    """demo-sync.js synchronised localStorage admin edits onto public pages.

    It existed to make a demo look live. With the demo admin removed it has no
    purpose, and leaving it would keep a parser-adjacent code path alive for
    nothing.
    """
    for name in ("demo-sync.js", "admin.js"):
        assert not (JS_DIR / name).exists(), f"{name} should have been removed"
        assert not (ROOT / "public" / "static" / "js" / name).exists(), (
            f"{name} still present in the public/ mirror"
        )


def test_no_template_references_a_removed_script():
    for template in (ROOT / "templates").rglob("*.html"):
        markup = template.read_text(encoding="utf-8")
        for name in ("demo-sync.js", "admin.js"):
            assert f"js/{name}" not in markup, f"{template.name} still loads {name}"
