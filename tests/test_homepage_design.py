"""Phase 2b: the homepage rebuilt to the brand sheet.

The valuable tests here are the ones that stop something false or broken
reaching a visitor: a `[000+]` placeholder rendering as a real statistic, a
fabricated testimonial, a logo strip of empty boxes, an animation that cannot
be switched off, or a brand colour used for text it fails contrast against.
"""

import json
import os
import re

import pytest
from fastapi.testclient import TestClient

from app import app
from services import ContentRepository


client = TestClient(app)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
repo = ContentRepository(content_dir=os.path.join(ROOT, "content"))

CSS_DIR = os.path.join(ROOT, "static", "css")


def css(name):
    with open(os.path.join(CSS_DIR, name), encoding="utf-8") as handle:
        return handle.read()


def home_html():
    return client.get("/").text


# ── placeholders must never reach a visitor ──────────────────────────────────

def test_draft_stats_are_withheld_from_the_page():
    """The brief asked for [000+] placeholders. They belong in the file, not
    on the live site — a visitor seeing "[000+] events delivered" reads it as
    a broken site, and a filled-in guess would be a lie."""
    html = home_html()
    assert "[000+]" not in html
    assert "[00]" not in html

    drafts = [s for s in (repo.home().get("stats") or []) if s.get("draft")]
    assert drafts, "expected unfilled stats to still be flagged draft"
    for stat in drafts:
        assert stat["value"] not in html, f"draft stat {stat['id']} leaked onto the page"


def test_only_real_stats_render():
    stats = repo.home_stats(destination_count=21)
    ids = {stat["id"] for stat in stats}
    assert "destinations" in ids
    assert "events" not in ids, "an unfilled 'events delivered' figure must not render"
    assert "years" not in ids
    # 24/7 support is a promise a delegate will test at 2am; it stays off until
    # the business confirms it staffs the line.
    assert "support" not in ids


def test_destination_stat_is_computed_not_typed():
    """The hero, the admin panel and the enquiry dropdown each previously
    carried a different hard-coded destination count."""
    real_count = len(repo.all_destinations())
    stats = {s["id"]: s["value"] for s in repo.home_stats(destination_count=real_count)}
    assert stats["destinations"] == str(real_count)
    assert real_count >= 21


def test_testimonial_section_is_absent_until_real_quotes_exist():
    """No placeholder quote, at all. An invented testimonial is the most
    damaging thing that could appear on this site, so there is no code path
    that renders one."""
    assert repo.testimonials() == [], "unexpected testimonial content in the repo"
    html = home_html()
    assert 'id="testimonials"' not in html
    assert "testimonial-card" not in html


def test_logo_strip_is_absent_until_clients_exist():
    """A row of grey placeholder boxes tells a visitor the company has no
    clients. Better to show nothing."""
    assert repo.clients() == []
    assert "logo-strip" not in home_html()


def test_proof_collections_document_the_permission_requirement():
    """Whoever fills these folders must know a logo needs written permission."""
    for folder in ("testimonials", "clients"):
        path = os.path.join(ROOT, "content", folder, "README.md")
        assert os.path.isfile(path), f"content/{folder}/README.md is missing"
        with open(path, encoding="utf-8") as handle:
            text = handle.read().lower()
        assert "permission" in text, f"content/{folder}/README.md omits the permission warning"


def test_hero_floating_cards_are_marked_as_format_examples():
    """They name event types and group sizes. The content file has to be
    explicit that these illustrate formats rather than claiming past events."""
    note = repo.home()["hero"].get("_cards_note", "")
    assert "TODO(ethpl)" in note
    assert "not claimed past events" in note


# ── motion ───────────────────────────────────────────────────────────────────

ANIMATED_SELECTORS = [
    "[data-enter-step]",
    ".hero-float-card",
    ".hero-forest-ring",
    ".btn-pulse",
    ".logo-strip-track",
]


def test_every_homepage_animation_is_disabled_under_reduced_motion():
    """Vestibular disorders and migraine make drifting and pulsing genuinely
    unpleasant, not merely a preference."""
    content = css("animations.css")
    blocks = re.findall(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n\}",
        content, re.DOTALL,
    )
    assert blocks, "no prefers-reduced-motion block found"
    combined = "\n".join(blocks)
    for selector in ANIMATED_SELECTORS:
        assert selector in combined, f"{selector} is animated but never disabled"


def test_animated_elements_do_not_start_invisible_without_a_reset():
    """`animation: both` leaves an element at its from-state if the animation
    never runs. The reduced-motion block has to force opacity back."""
    content = css("animations.css")
    reduced = re.search(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n\}",
        content, re.DOTALL,
    ).group(1)
    assert "opacity: 1 !important" in reduced
    assert "transform: none !important" in reduced


def test_hero_content_is_in_the_html_not_injected_by_script():
    """If the headline depended on JavaScript, a crawler or a failed script
    would see an empty hero."""
    html = home_html()
    headline = repo.home()["hero"]["headline"]
    assert headline in html
    # The destination tabs are progressive: the domestic set is server-rendered.
    assert 'data-home-dest-region="india"' in html


# ── brand palette ────────────────────────────────────────────────────────────

def luminance(hex_colour):
    channels = []
    value = hex_colour.lstrip("#")
    for index in (0, 2, 4):
        channel = int(value[index:index + 2], 16) / 255
        channels.append(
            channel / 12.92 if channel <= 0.03928
            else ((channel + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first, second):
    a, b = luminance(first), luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_brand_palette_is_defined_once_in_theme_css():
    """Every brand colour lives in theme.css as a token. A hex value typed
    into a template cannot be rebranded later."""
    content = css("theme.css")
    for token, value in (
        ("--brand-forest", "#2F5D27"),
        ("--brand-green", "#4E8A2E"),
        ("--brand-leaf", "#8CC152"),
        ("--brand-amber", "#9C5A12"),
        ("--brand-bark", "#7A5230"),
        ("--brand-cream", "#F7F5EE"),
        ("--brand-charcoal", "#1F2421"),
    ):
        assert f"{token}:" in content, f"{token} is not defined"
        assert value in content, f"{value} ({token}) is missing from theme.css"


def test_body_text_colours_meet_wcag_aa():
    """Measured, not assumed. Brand green #4E8A2E reaches only 4.20:1 on
    white, so it is deliberately NOT the link colour — Forest green is."""
    white, cream = "#FFFFFF", "#F7F5EE"
    assert contrast("#1F2421", cream) >= 4.5      # charcoal body text
    assert contrast("#2F5D27", white) >= 4.5      # forest links
    assert contrast("#2F5D27", cream) >= 4.5
    assert contrast(white, "#9C5A12") >= 4.5      # white on amber CTA
    assert contrast("#7A5230", cream) >= 4.5      # bark accent text

    # The two that fail, recorded so a future change cannot quietly promote
    # them to body text believing they pass.
    assert contrast("#4E8A2E", white) < 4.5
    assert contrast("#8CC152", white) < 4.5


def test_links_use_the_colour_that_passes_contrast():
    content = css("theme.css")
    match = re.search(r"--brand-link:\s*var\(([^)]+)\)", content)
    assert match, "--brand-link is not defined"
    assert match.group(1).strip() == "--leaf-700", (
        "--brand-link must resolve to Forest green (--leaf-700); Brand green "
        "fails AA at body size"
    )


def test_two_web_fonts_only():
    """The brand sheet allows two. A third cost every page a request on
    mobile and was used for almost nothing."""
    html = home_html()
    families = re.findall(r"family=([A-Za-z+]+)", html)
    assert set(families) == {"Poppins", "DM+Sans"}, f"unexpected fonts: {families}"
    assert "JetBrains" not in html


def test_amber_is_reserved_for_actions():
    """Amber is the action colour. If it is also the text colour, nothing on
    the page reads as clickable."""
    content = css("theme.css")
    assert "--primary:             var(--amber-cta)" in content
    link = re.search(r"--brand-link:\s*var\(([^)]+)\)", content).group(1)
    assert "amber" not in link


# ── enquiry chips ────────────────────────────────────────────────────────────

CHIP_VALUES = ["Conference", "Corporate Offsite", "Incentive Trip", "Educational Tour", "Exhibition"]


@pytest.mark.parametrize("value", CHIP_VALUES)
def test_each_chip_matches_a_real_event_type_option(value):
    """A chip whose value is absent from the select silently does nothing."""
    html = home_html()
    assert f'data-event-type="{value}"' in html, f"chip {value} is missing"
    options = set(re.findall(r'<option value="([^"]+)"', html))
    assert value in options, f"chip {value!r} is not an event_type option"


def test_chip_prefill_is_wired_in_the_controller():
    with open(os.path.join(ROOT, "static", "js", "app.js"), encoding="utf-8") as handle:
        js = handle.read()
    assert "presetEventType" in js
    assert "data-event-type" in js
    assert "#rfp-event-type" in js


# ── structure ────────────────────────────────────────────────────────────────

def test_homepage_sections_appear_in_the_brief_order():
    html = home_html()
    expected = [
        "hero-forest",        # 1 hero
        "stat-grid",          # 3 stats
        'id="services"',      # 4 services
        'id="destinations"',  # 5 destinations
        'id="why-ethpl"',     # 6 why
        'id="how-it-works"',  # 7 how it works
        'id="faq"',           # 9 faq
        'id="enquire"',       # 10 enquiry
    ]
    positions = []
    for marker in expected:
        index = html.find(marker)
        assert index != -1, f"section {marker} is missing"
        positions.append(index)
    assert positions == sorted(positions), "homepage sections are out of order"


def test_homepage_emits_faq_schema():
    html = home_html()
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.DOTALL
    )
    parsed = [json.loads(block) for block in blocks]
    faq = [block for block in parsed if block.get("@type") == "FAQPage"]
    assert faq, "homepage FAQ is not exposed as structured data"
    assert len(faq[0]["mainEntity"]) >= 4


def test_homepage_copy_is_editable_without_touching_a_template():
    """Hero copy, stats, benefits, steps and FAQs all come from content."""
    home = repo.home()
    for key in ("hero", "stats", "why_numbered", "how_it_works", "faqs"):
        assert home.get(key), f"home.json is missing {key}"
    assert home["hero"]["headline"] in home_html()


def test_components_toggled_with_hidden_also_disable_their_display_rule():
    """`display: block` beats the user-agent's `[hidden] { display: none }`.

    The destination tiles are toggled by setting the hidden attribute. Because
    `.dest-tile` also sets `display`, the hidden International tiles kept their
    layout box and the section ran to roughly 6000px on a phone. Any component
    that sets `display` and is toggled with `hidden` needs the paired rule.
    """
    content = css("components.css")
    assert ".dest-tile[hidden]" in content, (
        ".dest-tile sets display, so it needs an explicit [hidden] rule or the "
        "hidden attribute will not hide it"
    )
    # The paired rule must come before the display rule or be equally specific;
    # assert it actually sets display: none.
    match = re.search(r"\.dest-tile\[hidden\]\s*\{([^}]*)\}", content)
    assert match and "display: none" in match.group(1)
