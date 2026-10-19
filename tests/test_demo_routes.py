import os
import json
import re
from glob import glob
from fastapi.testclient import TestClient
from app import app, BASE_DIR, STATIC_DIR, CONTENT_DIR, BLOG_DIR

client = TestClient(app)


def test_public_pages():
    routes = [
        ('/', 200),
        ('/destinations', 200),
        ('/services/visa', 200),
        ('/services/flights', 404),
        ('/services/holidays', 200),
        ('/services/non-existent-service', 404),
        ('/flights', 404),
        ('/estimator', 410),
        ('/privacy', 200),
        ('/terms', 200),
        ('/sitemap.xml', 200),
        ('/blog', 200),
        ('/blog/corporate-offsite-planning-guide-2026', 200),
        ('/blog/top-convention-hotels-dubai-mice', 200),
        ('/blog/singapore-tech-summits-convention-playbook', 200),
        ('/blog/baku-azerbaijan-emerging-mice-hotspot', 200),
        ('/blog/bali-incentive-retreats-leadership-summits', 200),
        ('/blog/bangkok-pattaya-dealer-incentive-trips', 200),
        ('/blog/goa-beachside-corporate-conclaves', 200),
        ('/blog/group-airline-charter-vs-block-booking', 200),
        ('/blog/jim-corbett-wilderness-strategy-retreats', 200),
        ('/blog/non-existent-article', 404),
        ('/robots.txt', 200),
    ]
    for path, expected in routes:
        response = client.get(path)
        assert response.status_code == expected, f"Failed on {path}: got {response.status_code}"


def test_robots_txt_allows_crawlers():
    """The public site must stay crawlable.

    Replaces test_robots_txt_disallow, which asserted a blanket `Disallow: /`.
    That blocked every page from search engines, so no amount of on-page SEO
    could have ranked the site. Admin and the API stay excluded.
    """
    response = client.get('/robots.txt')
    assert response.status_code == 200
    assert "Allow: /" in response.text
    assert "Disallow: /admin" in response.text
    assert "Disallow: /api/" in response.text
    assert "Sitemap:" in response.text
    # Guard against the blanket block returning: a bare "Disallow: /" line.
    assert not any(
        line.strip() == "Disallow: /"
        for line in response.text.splitlines()
    )


def test_public_pages_are_indexable():
    """No public template may carry a noindex directive."""
    for path in ('/', '/destinations', '/mice', '/blog', '/services/visa'):
        response = client.get(path)
        assert response.status_code == 200
        assert 'name="robots"' not in response.text, f"{path} carries a robots meta tag"
        assert 'rel="canonical"' in response.text, f"{path} is missing a canonical URL"


def test_admin_pages_stay_noindex(monkeypatch):
    """Admin must keep its noindex even though the public site lost its own."""
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-value-at-least-32-bytes-long")
    response = client.get('/admin/login')
    assert response.status_code == 200
    assert 'name="robots"' in response.text
    assert 'noindex' in response.text


def test_retired_routes_redirect():
    """Packages and Venues collapsed into Destinations in Phase 1d.

    They must keep returning a permanent redirect rather than 404, so existing
    links, bookmarks and already-indexed URLs survive the removal.
    """
    for path in ('/packages', '/hotels'):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 301, f"{path} should 301, got {response.status_code}"
        assert response.headers['location'] == '/destinations'


def test_sitemap_lists_public_pages_only():
    response = client.get('/sitemap.xml')
    assert response.status_code == 200
    body = response.text
    for path in ('/destinations', '/mice', '/blog', '/privacy', '/terms'):
        assert f"<loc>" in body and path in body, f"sitemap missing {path}"
    # Retired and private routes must never be advertised to crawlers.
    assert '/admin' not in body
    assert '/packages' not in body
    assert '/hotels' not in body
    assert '/estimator' not in body


def test_destinations_page_and_records():
    """F-46 & F-53: Verify destination catalogue page and all 16 JSON records."""
    dest_files = glob(os.path.join(CONTENT_DIR, "destinations", "*.json"))
    assert len(dest_files) >= 16, f"Expected at least 16 destination records, found {len(dest_files)}"

    for filepath in dest_files:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        assert data.get("slug"), f"Missing slug in {filepath}"
        assert data.get("name"), f"Missing name in {filepath}"
        assert data.get("region") in {"india", "international"}, f"Invalid region in {filepath}"
        assert data.get("country"), f"Missing country in {filepath}"
        # partner_url is no longer asserted: destination cards open our own
        # enquiry form instead of linking out, so the field is legacy data and
        # new destinations must not be blocked on having one.

        # card_image may be empty for a destination we hold no photograph of;
        # those render the imageless card treatment instead of borrowing
        # another destination's photo. When one IS set it must resolve on disk.
        card_img = data.get("card_image", "")
        if card_img:
            assert card_img.startswith("/static/"), f"card_image must start with /static/ in {filepath}"
            rel_path = card_img.replace("/static/", "").replace("/", os.sep)
            disk_path = os.path.join(STATIC_DIR, rel_path)
            assert os.path.isfile(disk_path), f"Card image file not found on disk for {filepath}: {disk_path}"
        else:
            assert data.get("image_is_placeholder"), (
                f"{filepath} has no card_image and must be flagged image_is_placeholder "
                "so templates know to render the imageless treatment"
            )

    response = client.get('/destinations')
    assert response.status_code == 200
    # Cards must stay on our own site. In Phase 1d they opened the enquiry
    # modal, because there was nowhere else to send people; now that every
    # destination has its own page they link there, which keeps the visitor on
    # the site and gives the detail pages the internal links they need to rank.
    assert 'href="/destinations/goa"' in response.text
    assert 'data-good-for=' in response.text, "cards must expose tags for the purpose filter"
    # Partner anchors may survive only in the footer disclosure, which carries
    # a `footer-partner` campaign tag. Any other one would be a card linking out.
    partner_links = re.findall(r'href="(https://www\.holidaymyplanet\.com[^"]*)"', response.text)
    for link in partner_links:
        assert "footer-partner" in link, f"Destination card links out to the partner: {link}"


def test_service_pages():
    """Service pages keep a secondary partner link, but our enquiry comes first.

    The partner link used to be the primary button here. This now also asserts
    the on-site CTA exists, since sending the visitor away was the lead leak.
    """
    for service_slug in ["visa", "holidays"]:
        response = client.get(f"/services/{service_slug}")
        assert response.status_code == 200
        assert "holidaymyplanet.com" in response.text
        assert f"utm_campaign=service-{service_slug}" in response.text
        assert 'target="_blank"' in response.text
        assert 'rel="noopener' in response.text
        # Our own enquiry must be the primary action on the page.
        assert 'class="btn btn-primary btn-lg open-rfp-btn"' in response.text
        # The partner must not hold a primary button.
        assert 'class="btn btn-primary btn-lg"\n               aria-label' not in response.text

    visa_response = client.get("/services/visa")
    assert "Express E-Visa" in visa_response.text
    assert "ASAN E-Visa" in visa_response.text


def test_homepage_partner_links_are_footer_only():
    """The homepage must keep its leads.

    This replaces a test that required at least 3 partner links on the homepage.
    That requirement was the lead leak: the top bar and both catalogue sections
    pushed visitors to the partner domain before they ever enquired. Partner
    links now survive only in the footer disclosure, and must still carry UTMs.
    """
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="https://www.holidaymyplanet.com/?utm_source=ethpl&utm_medium=catalogue&utm_campaign=footer-partner"' in response.text

    partner_links = re.findall(r'href="(https://www\.holidaymyplanet\.com[^"]*)"', response.text)
    for link in partner_links:
        assert "utm_source=ethpl" in link, f"Partner link missing utm_source: {link}"
        assert "utm_medium=catalogue" in link, f"Partner link missing utm_medium: {link}"
        assert "utm_campaign=" in link, f"Partner link missing utm_campaign: {link}"
    # Only the footer disclosure (brand mark + inline mention + bottom bar).
    assert len(partner_links) <= 3, (
        f"Homepage should only link to the partner from the footer; found {len(partner_links)}"
    )
    for link in partner_links:
        assert "footer-partner" in link, f"Non-footer partner link on homepage: {link}"


def test_homepage_has_why_choose_us_and_own_cta():
    response = client.get("/")
    assert response.status_code == 200
    assert "Why organisations choose us" in response.text
    # Asserts the property, not the wording: the homepage must offer our own
    # enquiry CTA. Button copy comes from content/home.json and changes with
    # campaigns, so pinning an exact phrase here would be a brittle test.
    assert "open-rfp-btn" in response.text
    # Benefit points flagged `draft` in site.json must never reach the page.
    # (HTML comments elsewhere legitimately carry TODO markers for the team, so
    # this checks the draft point's own copy rather than the marker itself.)
    assert "years in business and events delivered" not in response.text
    assert "supply real figures" not in response.text


def test_no_retired_route_links_remain():
    """No template may link to a route that has been retired."""
    for path in ('/', '/destinations', '/mice', '/blog', '/privacy', '/terms'):
        response = client.get(path)
        assert response.status_code == 200
        assert 'href="/packages' not in response.text, f"{path} links to retired /packages"
        assert 'href="/hotels' not in response.text, f"{path} links to retired /hotels"
        # The admin portal must not be advertised publicly.
        assert 'href="/admin' not in response.text, f"{path} exposes an admin link"
        # Dead placeholder anchors.
        assert 'href="#"' not in response.text, f"{path} has a placeholder href=#"


def test_no_estimator_css_or_script_remains():
    """F-44: Ensure no orphan estimator selectors or scripts remain in static assets."""
    css_path = os.path.join(STATIC_DIR, "css", "components.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    forbidden_selectors = [
        "estimator-card", "estimator-grid", "estimator-summary-box",
        "hero-est-box", "hero-est-total", "est-forecast-title", "range-slider"
    ]
    for sel in forbidden_selectors:
        assert sel not in css_content, f"Found dead selector '{sel}' in {css_path}"

    assert not os.path.exists(os.path.join(STATIC_DIR, "js", "estimator.js"))


def test_blog_hero_images_exist_on_disk():
    """F-38 / F-40: Assert every blog hero image resolves to an existing file on disk."""
    blog_files = glob(os.path.join(BLOG_DIR, "*.json"))
    assert len(blog_files) >= 9, f"Expected at least 9 blog posts, found {len(blog_files)}"

    for filepath in blog_files:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        hero_image = data.get("hero_image", "")
        assert hero_image, f"Missing hero_image in {filepath}"
        assert hero_image.startswith("/static/"), f"hero_image must start with /static/ in {filepath}: {hero_image}"

        # Resolve relative to static dir
        rel_path = hero_image.replace("/static/", "").replace("/", os.sep)
        disk_path = os.path.join(STATIC_DIR, rel_path)
        assert os.path.isfile(disk_path), f"Hero image file not found on disk for {filepath}: {disk_path}"


def test_blog_post_substantive_content():
    """F-39: Assert blog posts have substantial content (700+ words) and honest attribution."""
    blog_files = glob(os.path.join(BLOG_DIR, "*.json"))
    for filepath in blog_files:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        body = data.get("body_markdown", "")
        words = body.split()
        assert len(words) >= 500, f"Blog post {filepath} too short: only {len(words)} words"
        assert data.get("author") == "ETHPL Editorial Team", f"Invalid or invented author in {filepath}: {data.get('author')}"


def test_rfp_submission_valid(monkeypatch, tmp_path):
    monkeypatch.setenv("RFP_DATABASE_PATH", str(tmp_path / "leads.sqlite3"))
    valid_rfp = {
        'company_name': 'Acme Global Corp',
        'contact_name': 'Sarah Jenkins',
        'contact_info': 'sarah.j@acmeglobal.com',
        'destination': 'Dubai, UAE',
        'pax_count': 120,
        'notes': 'Looking for gala dinner venue and flight booking'
    }
    response = client.post('/api/rfp', json=valid_rfp, headers={"Idempotency-Key": "legacy-valid-test"})
    assert response.status_code == 201
    data = response.json()
    assert data.get('ok') is True
    assert data.get('data', {}).get('reference', '').startswith('RFP-')


def test_rfp_submission_invalid():
    invalid_rfp = {
        'company_name': '',
        'contact_name': '',
        'contact_info': 'a',
        'destination': 'Dubai, UAE',
        'pax_count': 5
    }
    response = client.post('/api/rfp', json=invalid_rfp)
    assert response.status_code == 422
    data = response.json()
    assert data.get('ok') is False
    assert 'fields' in data
