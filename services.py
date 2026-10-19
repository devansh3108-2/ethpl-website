import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path


logger = logging.getLogger(__name__)


class ContentError(Exception):
    pass


class ContentRepository:
    def __init__(self, blog_dir: str | Path | None = None, content_dir: str | Path | None = None):
        if content_dir:
            self.content_dir = Path(content_dir)
            self.blog_dir = self.content_dir / "blog"
        elif blog_dir:
            self.blog_dir = Path(blog_dir)
            self.content_dir = self.blog_dir.parent
        else:
            self.content_dir = Path("content")
            self.blog_dir = self.content_dir / "blog"

        self.destinations_dir = self.content_dir / "destinations"
        self.services_dir = self.content_dir / "services"
        self.audiences_dir = self.content_dir / "audiences"
        self.site_json_path = self.content_dir / "site.json"

    # Slugs are used to build filesystem paths, so they are restricted to a
    # safe alphabet rather than sanitised. A slug containing a dot or a
    # separator is rejected outright, not cleaned up.
    SLUG_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")

    @classmethod
    def _valid_slug(cls, slug: str) -> bool:
        return bool(slug) and not (set(slug) - cls.SLUG_ALPHABET)

    def _load_collection(self, directory: Path, sort_key="order"):
        items = []
        if not directory.exists():
            return items
        for path in directory.glob("*.json"):
            try:
                items.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                logger.warning("Unable to load %s (%s)", path.name, type(exc).__name__)
        return sorted(items, key=lambda item: (item.get(sort_key, 99), item.get("name", "")))

    def _load_one(self, directory: Path, slug: str, label: str):
        if not self._valid_slug(slug):
            return None
        path = directory / f"{slug}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("Unable to load %s %s (%s)", label, path.name, type(exc).__name__)
            raise ContentError(f"{label} content is unavailable") from exc

    def all_services(self):
        """The six MICE services ETHPL delivers itself."""
        return self._load_collection(self.services_dir)

    def service_by_slug(self, slug: str):
        return self._load_one(self.services_dir, slug, "Service")

    def all_audiences(self):
        return self._load_collection(self.audiences_dir)

    def audience_by_slug(self, slug: str):
        return self._load_one(self.audiences_dir, slug, "Audience")

    def home(self):
        """Homepage copy, stats and FAQs."""
        path = self.content_dir / "home.json"
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("Unable to load home.json (%s)", type(exc).__name__)
            return {}

    def home_stats(self, destination_count: int = 0):
        """Stat tiles, with drafts withheld and computed values resolved.

        A stat flagged `draft` is a placeholder the business has not filled in.
        Those are dropped here rather than in the template, so no path through
        the site can render "[000+] events delivered" to a visitor.
        """
        resolved = []
        for stat in (self.home().get("stats") or []):
            if stat.get("draft") or not stat.get("value"):
                continue
            value = stat["value"]
            if value == "auto:destinations":
                value = str(destination_count)
            resolved.append({**stat, "value": value})
        return resolved

    def testimonials(self):
        """Client quotes. Empty until the business supplies real ones."""
        return self._load_collection(self.content_dir / "testimonials")

    def clients(self):
        """Client logos. Empty until written permission is held for each."""
        return self._load_collection(self.content_dir / "clients")

    def all_posts(self):
        posts = []
        if not self.blog_dir.exists():
            return posts
        for path in self.blog_dir.glob("*.json"):
            try:
                posts.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                logger.warning("Unable to load blog file %s (%s)", path.name, type(exc).__name__)
        return sorted(posts, key=lambda post: post.get("publish_date", ""), reverse=True)

    def by_slug(self, slug: str):
        if not slug or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in slug):
            return None
        path = self.blog_dir / f"{slug}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("Unable to load blog file %s (%s)", path.name, type(exc).__name__)
            raise ContentError("Blog content is unavailable") from exc

    def all_destinations(self):
        destinations = []
        if not self.destinations_dir.exists():
            return destinations
        for path in self.destinations_dir.glob("*.json"):
            try:
                destinations.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                logger.warning("Unable to load destination file %s (%s)", path.name, type(exc).__name__)
        return sorted(destinations, key=lambda d: (d.get("sort_order", 99), d.get("name", "")))

    def featured_destinations(self):
        return [d for d in self.all_destinations() if d.get("featured")]

    def destination_by_slug(self, slug: str):
        if not slug or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in slug):
            return None
        path = self.destinations_dir / f"{slug}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("Unable to load destination file %s (%s)", path.name, type(exc).__name__)
            raise ContentError("Destination content is unavailable") from exc

    def site_config(self):
        if not self.site_json_path.is_file():
            return {}
        try:
            return json.loads(self.site_json_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("Unable to load site.json (%s)", type(exc).__name__)
            return {}

    def service_by_id(self, service_id: str):
        config = self.site_config()
        services = config.get("external_services", [])
        for svc in services:
            if svc.get("id") == service_id or svc.get("slug") == service_id:
                return svc
        return None

    # Brand strings, benefit points and legal copy are read from site.json so
    # templates never hard-code them. Each accessor falls back to a safe default
    # rather than raising, because a missing content file must not take the site
    # down — a page with a plain brand name still converts.
    DEFAULT_BRAND = {
        "name": "ETHPL",
        "fullName": "ETHPL Travel & Hospitality Pvt Ltd",
        "tagline": "Corporate Travel & Event Planning",
    }

    def brand(self):
        brand = dict(self.DEFAULT_BRAND)
        configured = self.site_config().get("brand") or {}
        brand.update({key: value for key, value in configured.items() if value})
        return brand

    def why_us(self):
        """Benefit points for the 'Why Choose ETHPL' section.

        Points flagged `draft` are placeholders awaiting real figures from the
        business and are withheld from the public site — publishing an unfilled
        claim is worse than publishing one fewer benefit.
        """
        points = self.site_config().get("why_us") or []
        return [
            point for point in points
            if point.get("title") and not point.get("draft")
        ]

    def legal_page(self, slug: str):
        """Copy for /privacy and /terms."""
        pages = self.site_config().get("legal_pages") or {}
        return pages.get(slug)


class LeadStoreUnavailable(Exception):
    pass


# One definition of the lead columns, shared by both repositories so the SQLite
# and Postgres schemas cannot drift apart.
LEAD_COLUMNS = (
    "reference",
    "idempotency_key",
    "company_name",
    "contact_name",
    "contact_info",
    "destination",
    "pax_count",
    "notes",
    "organisation_type",
    "event_type",
    "travel_window",
    "created_at",
)

# Fields echoed back to the browser on success. Deliberately a subset: the
# response is public, so it carries no contact details.
PUBLIC_LEAD_FIELDS = ("reference", "company_name", "destination", "pax_count")


def new_lead_reference() -> str:
    return f"RFP-{uuid.uuid4().hex.upper()}"


def lead_row_values(payload: dict, reference: str, idempotency_key: str, created_at: str):
    """Positional values matching LEAD_COLUMNS."""
    return (
        reference,
        idempotency_key,
        payload["company_name"],
        payload["contact_name"],
        payload["contact_info"],
        payload["destination"],
        payload["pax_count"],
        payload.get("notes"),
        payload.get("organisation_type"),
        payload.get("event_type"),
        payload.get("travel_window"),
        created_at,
    )


class SQLiteLeadRepository:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    # Columns added after the table first shipped. CREATE TABLE IF NOT EXISTS
    # will not alter a table that already exists, so an existing lead database
    # needs each one added explicitly or the qualifying answers are dropped on
    # insert.
    ADDED_COLUMNS = (
        ("organisation_type", "TEXT"),
        ("event_type", "TEXT"),
        ("travel_window", "TEXT"),
    )

    def _initialize(self):
        try:
            with self._connection() as connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS leads (
                        reference TEXT PRIMARY KEY,
                        idempotency_key TEXT UNIQUE,
                        company_name TEXT NOT NULL,
                        contact_name TEXT NOT NULL,
                        contact_info TEXT NOT NULL,
                        destination TEXT NOT NULL,
                        pax_count INTEGER NOT NULL,
                        notes TEXT,
                        organisation_type TEXT,
                        event_type TEXT,
                        travel_window TEXT,
                        created_at TEXT NOT NULL
                    )"""
                )
                existing = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(leads)").fetchall()
                }
                for column, column_type in self.ADDED_COLUMNS:
                    if column not in existing:
                        connection.execute(
                            f"ALTER TABLE leads ADD COLUMN {column} {column_type}"
                        )
        except sqlite3.Error as exc:
            raise LeadStoreUnavailable("Lead storage is unavailable") from exc

    def save(self, payload: dict, idempotency_key: str, created_at: str):
        reference = f"RFP-{uuid.uuid4().hex.upper()}"
        try:
            with self._connection() as connection:
                existing = connection.execute(
                    "SELECT reference, company_name, destination, pax_count, created_at FROM leads WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    return self._public(existing), False
                connection.execute(
                    """INSERT INTO leads
                    (reference, idempotency_key, company_name, contact_name, contact_info,
                     destination, pax_count, notes, organisation_type, event_type,
                     travel_window, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        reference,
                        idempotency_key,
                        payload["company_name"],
                        payload["contact_name"],
                        payload["contact_info"],
                        payload["destination"],
                        payload["pax_count"],
                        payload.get("notes"),
                        payload.get("organisation_type"),
                        payload.get("event_type"),
                        payload.get("travel_window"),
                        created_at,
                    ),
                )
                return {
                    "reference": reference,
                    "company_name": payload["company_name"],
                    "destination": payload["destination"],
                    "pax_count": payload["pax_count"],
                    "timestamp": created_at,
                }, True
        except sqlite3.Error as exc:
            raise LeadStoreUnavailable("Lead storage is unavailable") from exc

    @staticmethod
    def _public(row):
        return {
            "reference": row[0],
            "company_name": row[1],
            "destination": row[2],
            "pax_count": row[3],
            "timestamp": row[4],
        }

    LIST_SQL = """SELECT reference, created_at, company_name, organisation_type,
               contact_name, contact_info, event_type, destination,
               travel_window, pax_count, notes
        FROM leads ORDER BY created_at DESC LIMIT ?"""

    def list_leads(self, limit: int = 200):
        """Most recent leads first.

        Mirrors the Postgres implementation so the inbox renders identically
        whichever store is configured.
        """
        try:
            with self._connection() as connection:
                rows = connection.execute(self.LIST_SQL, (int(limit),)).fetchall()
        except sqlite3.Error as exc:
            raise LeadStoreUnavailable("Lead storage is unavailable") from exc
        return [dict(zip(LEAD_LIST_COLUMNS, row)) for row in rows]


class FixedWindowRateLimiter:
    def __init__(self):
        self._entries = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int):
        now = time.monotonic()
        with self._lock:
            started, count = self._entries.get(key, (now, 0))
            if now - started >= window_seconds:
                started, count = now, 0
            if count >= limit:
                return False, max(1, int(window_seconds - (now - started)))
            self._entries[key] = (started, count + 1)
            return True, 0

    def clear(self):
        with self._lock:
            self._entries.clear()



# Columns the leads inbox shows. Contact details are included because the
# whole point of the page is for sales to act on a lead; the page itself sits
# behind the admin session and is sent noindex.
LEAD_LIST_COLUMNS = (
    "reference", "created_at", "company_name", "organisation_type",
    "contact_name", "contact_info", "event_type", "destination",
    "travel_window", "pax_count", "notes",
)

class PostgresLeadRepository:
    """Lead storage for the deployed site.

    Vercel's filesystem is disposable, so the SQLite repository below cannot
    retain anything in production — every enquiry was lost. This writes to a
    hosted Postgres (Neon / Supabase) given a DATABASE_URL.

    psycopg is imported lazily so the app still boots, and local development
    still works on SQLite, when the driver is absent.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._initialize()

    def _driver(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised via mocks
            raise LeadStoreUnavailable(
                "psycopg is not installed; cannot reach the lead database"
            ) from exc
        return psycopg

    @contextmanager
    def _connection(self):
        psycopg = self._driver()
        try:
            # connect_timeout keeps a sleeping serverless database from holding
            # the request open until the platform's own timeout kills it.
            connection = psycopg.connect(self.dsn, connect_timeout=5)
        except Exception as exc:
            raise LeadStoreUnavailable("Lead storage is unavailable") from exc
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        try:
            with self._connection() as connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS leads (
                        reference TEXT PRIMARY KEY,
                        idempotency_key TEXT UNIQUE,
                        company_name TEXT NOT NULL,
                        contact_name TEXT NOT NULL,
                        contact_info TEXT NOT NULL,
                        destination TEXT NOT NULL,
                        pax_count INTEGER NOT NULL,
                        notes TEXT,
                        organisation_type TEXT,
                        event_type TEXT,
                        travel_window TEXT,
                        created_at TEXT NOT NULL
                    )"""
                )
        except LeadStoreUnavailable:
            raise
        except Exception as exc:
            raise LeadStoreUnavailable("Lead storage is unavailable") from exc

    # SQL is written out literally rather than assembled from the column
    # tuples at call time. Nothing user-supplied ever reaches these strings —
    # values go in as bound parameters — but a literal statement is easier to
    # review and does not read as a string-built query to a scanner.
    # test_lead_delivery.py asserts these stay in step with LEAD_COLUMNS.
    INSERT_SQL = """INSERT INTO leads (
            reference, idempotency_key, company_name, contact_name,
            contact_info, destination, pax_count, notes, organisation_type,
            event_type, travel_window, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING reference, company_name, destination, pax_count, created_at"""

    SELECT_BY_KEY_SQL = """SELECT reference, company_name, destination, pax_count, created_at
        FROM leads WHERE idempotency_key = %s"""

    LIST_SQL = """SELECT reference, created_at, company_name, organisation_type,
               contact_name, contact_info, event_type, destination,
               travel_window, pax_count, notes
        FROM leads ORDER BY created_at DESC LIMIT %s"""

    def save(self, payload: dict, idempotency_key: str, created_at: str):
        reference = new_lead_reference()
        try:
            with self._connection() as connection:
                # ON CONFLICT settles idempotency inside the statement. A
                # SELECT-then-INSERT would let two concurrent retries of the
                # same submission both pass the check and insert twice.
                row = connection.execute(
                    self.INSERT_SQL,
                    lead_row_values(payload, reference, idempotency_key, created_at),
                ).fetchone()
                if row is not None:
                    return self._public(row), True

                # DO NOTHING fired: this key was already stored. Return the
                # original record so a retry is not reported as a new lead.
                existing = connection.execute(
                    self.SELECT_BY_KEY_SQL,
                    (idempotency_key,),
                ).fetchone()
                if existing is None:
                    raise LeadStoreUnavailable("Lead storage is unavailable")
                return self._public(existing), False
        except LeadStoreUnavailable:
            raise
        except Exception as exc:
            raise LeadStoreUnavailable("Lead storage is unavailable") from exc

    @staticmethod
    def _public(row):
        data = dict(zip(PUBLIC_LEAD_FIELDS, row))
        data["timestamp"] = row[len(PUBLIC_LEAD_FIELDS)]
        return data

    def list_leads(self, limit: int = 200):
        """Most recent leads first, for the admin inbox.

        Capped rather than paginated: an inbox showing the last couple of
        hundred enquiries is what the sales desk actually works from, and an
        uncapped query on a growing table would eventually time out the
        serverless function.
        """
        try:
            with self._connection() as connection:
                rows = connection.execute(self.LIST_SQL, (int(limit),)).fetchall()
        except LeadStoreUnavailable:
            raise
        except Exception as exc:
            raise LeadStoreUnavailable("Lead storage is unavailable") from exc
        return [dict(zip(LEAD_LIST_COLUMNS, row)) for row in rows]


class EmailNotifier:
    """Sends the sales team an alert for every enquiry.

    Two backends, both on the standard library so no runtime dependency is
    added: Resend's HTTP API when RESEND_API_KEY is set, otherwise SMTP when
    SMTP_HOST is set. Unconfigured is a valid state — `enabled` is False and
    nothing is attempted.

    send() never raises. A failed notification must not fail a submission that
    was already stored; the caller decides what to do with the False.
    """

    def __init__(
        self,
        sales_email: str | None = None,
        from_email: str | None = None,
        resend_api_key: str | None = None,
        smtp_host: str | None = None,
        smtp_port: int = 587,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
    ):
        self.sales_email = sales_email
        self.from_email = from_email or "enquiries@ethpl.com"
        self.resend_api_key = resend_api_key
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password

    @classmethod
    def from_env(cls, env=None):
        env = env if env is not None else os.environ
        return cls(
            sales_email=env.get("SALES_EMAIL"),
            from_email=env.get("LEAD_FROM_EMAIL"),
            resend_api_key=env.get("RESEND_API_KEY"),
            smtp_host=env.get("SMTP_HOST"),
            smtp_port=int(env.get("SMTP_PORT", "587")),
            smtp_user=env.get("SMTP_USER"),
            smtp_password=env.get("SMTP_PASSWORD"),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.sales_email and (self.resend_api_key or self.smtp_host))

    @staticmethod
    def compose(payload: dict, reference: str, stored: bool) -> tuple[str, str]:
        subject = (
            f"New enquiry: {payload.get('company_name', 'Unknown')}"
            f" — {payload.get('event_type') or 'event'}"
            f" — {payload.get('pax_count', '?')} pax"
        )
        lines = [
            f"Reference: {reference}",
            "",
            f"Organisation:  {payload.get('company_name', '-')}",
            f"Type:          {payload.get('organisation_type') or '-'}",
            f"Contact:       {payload.get('contact_name', '-')}",
            f"Reach them at: {payload.get('contact_info', '-')}",
            "",
            f"Event:         {payload.get('event_type') or '-'}",
            f"Destination:   {payload.get('destination', '-')}",
            f"Dates:         {payload.get('travel_window') or 'not given'}",
            f"Group size:    {payload.get('pax_count', '-')}",
            "",
            "Notes:",
            (payload.get("notes") or "(none)"),
        ]
        if not stored:
            lines += [
                "",
                "-- WARNING --------------------------------------------------",
                "The lead database was unreachable, so this enquiry exists ONLY",
                "in this email. Copy it somewhere safe before replying.",
                "-------------------------------------------------------------",
            ]
        lines += [
            "",
            "Reply within the hour if you can — response speed is the single",
            "biggest factor in winning these.",
        ]
        return subject, "\n".join(lines)

    def send(self, payload: dict, reference: str, stored: bool = True) -> bool:
        if not self.enabled:
            return False
        subject, body = self.compose(payload, reference, stored)
        try:
            if self.resend_api_key:
                return self._send_via_resend(subject, body)
            return self._send_via_smtp(subject, body)
        except Exception as exc:
            # Never propagate: the enquiry may already be saved.
            logger.warning("Lead notification failed (%s)", type(exc).__name__)
            return False

    # Fixed endpoint, never built from configuration or user input.
    RESEND_ENDPOINT = "https://api.resend.com/emails"

    def _send_via_resend(self, subject: str, body: str) -> bool:
        import json as json_module
        import urllib.request

        # Re-checked at the call site so the scheme is verified in code and not
        # merely by reading the constant above. urlopen on a file:// or custom
        # scheme is the risk this guards against.
        if not self.RESEND_ENDPOINT.startswith("https://"):
            raise ValueError("Resend endpoint must be HTTPS")

        request = urllib.request.Request(
            self.RESEND_ENDPOINT,
            data=json_module.dumps(
                {
                    "from": self.from_email,
                    "to": [self.sales_email],
                    "subject": subject,
                    "text": body,
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.resend_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=8) as response:  # nosec B310 - scheme asserted https above; endpoint is a module constant
            return 200 <= response.status < 300

    def _send_via_smtp(self, subject: str, body: str) -> bool:
        import smtplib
        from email.message import EmailMessage

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.from_email
        message["To"] = self.sales_email
        message.set_content(body)

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=8) as smtp:
            smtp.starttls()
            if self.smtp_user and self.smtp_password:
                smtp.login(self.smtp_user, self.smtp_password)
            smtp.send_message(message)
        return True


def build_lead_repository(env=None):
    """Pick the lead store from the environment.

    DATABASE_URL wins, because that is what production sets. RFP_DATABASE_PATH
    keeps local development on SQLite. Neither configured returns None, and the
    caller degrades honestly rather than pretending the lead was saved.
    """
    env = env if env is not None else os.environ
    dsn = env.get("DATABASE_URL")
    if dsn:
        return PostgresLeadRepository(dsn)
    path = env.get("RFP_DATABASE_PATH")
    if path:
        return SQLiteLeadRepository(path)
    return None


class StrapiUnavailable(Exception):
    pass


class StrapiContentRepository:
    """Content from Strapi, with the local JSON files as a safety net.

    Phase 3 moves content editing to Strapi. Strapi runs as a separate Node
    service with its own database, so it is a dependency the public site does
    not control and cannot assume is up.

    The rule here: **a Strapi outage must never take the public site down.**
    Every read falls back to the JSON files already in the repository, which
    are a complete and valid copy of the content. The worst case is that the
    site serves slightly stale content until Strapi returns — not a 500.

    Results are cached for CACHE_TTL_SECONDS. Without it, one page render
    would make a separate HTTP call for destinations, services, audiences and
    the nav, several times over, on every request.
    """

    CACHE_TTL_SECONDS = 60

    # Strapi collection (plural API id) -> the method on the local repository
    # that returns the same shape.
    COLLECTIONS = {
        "destinations": "all_destinations",
        "services": "all_services",
        "audiences": "all_audiences",
        "testimonials": "testimonials",
        "clients": "clients",
    }

    def __init__(self, base_url: str, token: str, fallback: "ContentRepository", timeout: float = 4.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.fallback = fallback
        self.timeout = timeout
        self._cache = {}
        self._lock = threading.Lock()

    # ── transport ───────────────────────────────────────────────────────────

    def _fetch(self, collection: str):
        import urllib.error
        import urllib.parse
        import urllib.request

        if not self.base_url.startswith(("https://", "http://")):
            raise StrapiUnavailable("STRAPI_URL must be an absolute http(s) URL")
        # Only https in production. http is allowed for a local Strapi during
        # development, where the token is not a real secret.
        if not self.base_url.startswith("https://") and not _is_local_url(self.base_url):
            raise StrapiUnavailable("STRAPI_URL must use HTTPS outside local development")

        query = urllib.parse.urlencode({"pagination[pageSize]": 200, "populate": "*"})
        url = f"{self.base_url}/api/{urllib.parse.quote(collection)}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310 - scheme validated above
                if not 200 <= response.status < 300:
                    raise StrapiUnavailable(f"Strapi returned {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
        except StrapiUnavailable:
            raise
        except Exception as exc:
            raise StrapiUnavailable(f"Strapi request failed: {type(exc).__name__}") from exc

        entries = payload.get("data")
        if not isinstance(entries, list):
            raise StrapiUnavailable("Unexpected Strapi response shape")
        return [self._flatten(entry) for entry in entries]

    @staticmethod
    def _flatten(entry):
        """Strapi v4 nests fields under `attributes`; v5 does not.

        Handling both means an editor upgrading Strapi does not silently empty
        the site.
        """
        if isinstance(entry, dict) and isinstance(entry.get("attributes"), dict):
            flat = dict(entry["attributes"])
            flat.setdefault("id", entry.get("id"))
            return flat
        return dict(entry) if isinstance(entry, dict) else {}

    # ── caching ─────────────────────────────────────────────────────────────

    def _cached(self, collection: str):
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(collection)
            if hit and now - hit[0] < self.CACHE_TTL_SECONDS:
                return hit[1]

        try:
            items = self._fetch(collection)
        except StrapiUnavailable as exc:
            logger.warning(
                "Strapi unavailable for %s (%s); serving local content", collection, exc
            )
            return None

        with self._lock:
            self._cache[collection] = (now, items)
        return items

    def _collection(self, collection: str, sort_key="order"):
        items = self._cached(collection)
        if items is None:
            # Fall back to the JSON files. This is the whole point of the class.
            return getattr(self.fallback, self.COLLECTIONS[collection])()
        return sorted(items, key=lambda item: (item.get(sort_key, 99), item.get("name", "")))

    # ── ContentRepository interface ─────────────────────────────────────────
    # Anything Strapi does not own is delegated straight to the local files.

    def all_destinations(self):
        items = self._cached("destinations")
        if items is None:
            return self.fallback.all_destinations()
        return sorted(items, key=lambda d: (d.get("sort_order", 99), d.get("name", "")))

    def featured_destinations(self):
        return [d for d in self.all_destinations() if d.get("featured")]

    def destination_by_slug(self, slug: str):
        if not ContentRepository._valid_slug(slug):
            return None
        for destination in self.all_destinations():
            if destination.get("slug") == slug:
                return destination
        return None

    def all_services(self):
        return self._collection("services")

    def service_by_slug(self, slug: str):
        if not ContentRepository._valid_slug(slug):
            return None
        for service in self.all_services():
            if service.get("slug") == slug:
                return service
        return None

    def all_audiences(self):
        return self._collection("audiences")

    def audience_by_slug(self, slug: str):
        if not ContentRepository._valid_slug(slug):
            return None
        for audience in self.all_audiences():
            if audience.get("slug") == slug:
                return audience
        return None

    def testimonials(self):
        return self._collection("testimonials")

    def clients(self):
        return self._collection("clients")

    def __getattr__(self, name):
        """Delegate everything else — blog posts, site config, brand, home — to
        the local repository, so adding a Strapi collection later is additive
        rather than a rewrite."""
        return getattr(self.fallback, name)


def _is_local_url(url: str) -> bool:
    from urllib.parse import urlsplit
    host = (urlsplit(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def build_content_repository(content_dir, env=None):
    """Strapi when configured, local JSON files otherwise.

    Both paths are fully supported. The site is designed to run indefinitely on
    the JSON files alone, so this returning the local repository is a normal
    operating state and not a degraded one.
    """
    env = env if env is not None else os.environ
    local = ContentRepository(content_dir=content_dir)
    base_url, token = env.get("STRAPI_URL"), env.get("STRAPI_TOKEN")
    if base_url and token:
        return StrapiContentRepository(base_url=base_url, token=token, fallback=local)
    return local


# ==========================================================================
# SITE ASSET STORE — editable hero photos (and future image settings)
#
# The homepage hero shows two photos the admin can replace from
# /admin/appearance without a code deploy. On Vercel the filesystem is
# disposable, so the images cannot live in the repo once uploaded; they go
# into the SAME database that captures leads (DATABASE_URL in production,
# a local SQLite file in development), keyed by slot. A tiny `/media/<key>`
# route serves the bytes. Reusing the lead database means the business sets
# up ONE thing, not two.
#
# Like the lead store, this degrades honestly: with no database configured
# the admin page explains what to set and the homepage shows its branded
# placeholder rather than pretending a photo was saved.
# ==========================================================================

class AssetStoreUnavailable(Exception):
    pass


# Only these slots exist; an upload to any other key is rejected before it
# reaches the database.
HERO_PHOTO_KEYS = ("hero-1", "hero-2")

# What the admin upload form accepts. Kept deliberately small: these are the
# formats every browser renders and that compress well for a hero image.
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB — a hero photo has no reason to exceed this.


class SiteAssetStore:
    """Binary site assets (hero photos) in the lead database.

    One row per slot in a `site_assets` table. SQLite locally, Postgres in
    production — the same split the lead store uses, chosen from the same
    environment variables so there is nothing extra to configure.
    """

    def __init__(self, dsn: str | None = None, path: str | None = None):
        # Exactly one backend is set. `dsn` → Postgres, `path` → SQLite.
        self.dsn = dsn
        self.path = path
        self._placeholder = "%s" if dsn else "?"

    @classmethod
    def from_env(cls, env=None):
        env = env if env is not None else os.environ
        dsn = env.get("DATABASE_URL")
        if dsn:
            return cls(dsn=dsn)
        path = env.get("RFP_DATABASE_PATH")
        if path:
            return cls(path=path)
        return None

    @contextmanager
    def _connection(self):
        if self.dsn:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise AssetStoreUnavailable("psycopg is not installed") from exc
            try:
                connection = psycopg.connect(self.dsn, connect_timeout=5)
            except Exception as exc:
                raise AssetStoreUnavailable("Asset storage is unavailable") from exc
            try:
                with connection:
                    yield connection
            finally:
                connection.close()
        else:
            try:
                connection = sqlite3.connect(self.path, timeout=5)
            except sqlite3.Error as exc:
                raise AssetStoreUnavailable("Asset storage is unavailable") from exc
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def _ensure_schema(self, connection):
        data_type = "BYTEA" if self.dsn else "BLOB"
        connection.execute(
            f"""CREATE TABLE IF NOT EXISTS site_assets (
                    key          TEXT PRIMARY KEY,
                    content_type TEXT NOT NULL,
                    data         {data_type} NOT NULL,
                    alt          TEXT NOT NULL DEFAULT '',
                    updated_at   TEXT NOT NULL
                )"""
        )

    def put(self, key: str, data: bytes, content_type: str, alt: str, updated_at: str):
        if key not in HERO_PHOTO_KEYS:
            raise ValueError(f"unknown asset key: {key!r}")
        ph = self._placeholder
        try:
            with self._connection() as connection:
                self._ensure_schema(connection)
                connection.execute(
                    f"""INSERT INTO site_assets (key, content_type, data, alt, updated_at)
                        VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
                        ON CONFLICT (key) DO UPDATE SET
                            content_type = excluded.content_type,
                            data         = excluded.data,
                            alt          = excluded.alt,
                            updated_at   = excluded.updated_at""",
                    (key, content_type, data, alt, updated_at),
                )
        except AssetStoreUnavailable:
            raise
        except Exception as exc:
            raise AssetStoreUnavailable("Asset storage is unavailable") from exc

    def get(self, key: str):
        """(content_type, bytes) for one slot, or None if it has no photo."""
        if key not in HERO_PHOTO_KEYS:
            return None
        ph = self._placeholder
        try:
            with self._connection() as connection:
                self._ensure_schema(connection)
                row = connection.execute(
                    f"SELECT content_type, data FROM site_assets WHERE key = {ph}",
                    (key,),
                ).fetchone()
        except AssetStoreUnavailable:
            raise
        except Exception as exc:
            raise AssetStoreUnavailable("Asset storage is unavailable") from exc
        if not row:
            return None
        return row[0], bytes(row[1])

    def list_meta(self) -> dict:
        """{key: {content_type, alt, updated_at}} for every slot that has a
        photo. No image bytes — this feeds the homepage and the admin form."""
        try:
            with self._connection() as connection:
                self._ensure_schema(connection)
                rows = connection.execute(
                    "SELECT key, content_type, alt, updated_at FROM site_assets"
                ).fetchall()
        except AssetStoreUnavailable:
            raise
        except Exception as exc:
            raise AssetStoreUnavailable("Asset storage is unavailable") from exc
        return {
            row[0]: {"content_type": row[0 + 1], "alt": row[2], "updated_at": row[3]}
            for row in rows
            if row[0] in HERO_PHOTO_KEYS
        }


def build_site_asset_store(env=None):
    """The asset store from the environment, or None when no database is set.

    DATABASE_URL (production) wins; RFP_DATABASE_PATH keeps local development
    on SQLite — exactly like build_lead_repository, so the same one database
    serves both leads and editable images.
    """
    return SiteAssetStore.from_env(env)
