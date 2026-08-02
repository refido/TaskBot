import base64
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

from src.config import Config
from src.infrastructure.browser.page_objects.dashboard_page import Dashboard
from src.infrastructure.browser.page_objects.login_page import Login
from src.infrastructure.sessions.xhr_tracker import XHRTracker
from src.logging_utils import log_print, logger

CHROMIUM_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
DEFAULT_NETWORK_WAIT_MS = 3000


@dataclass(frozen=True)
class SessionArtifacts:
    operator: str
    artifact_dir: Path
    profile_dir: Path
    cookie_count: int
    xhr_count: int


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "account"


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)

    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")

    if isinstance(value, datetime):
        return value.isoformat()

    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, default=json_default),
        encoding="utf-8",
    )


def datetime_to_rfc1123(value: datetime | None) -> str | None:
    if value is None:
        return None

    return format_datetime(value.astimezone(UTC), usegmt=True)


def unix_seconds_to_datetime(value: Any) -> datetime | None:
    if value in (None, "", -1):
        return None

    try:
        seconds = float(value)
    except TypeError, ValueError:
        return None

    if not math.isfinite(seconds) or seconds < 0:
        return None

    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except OverflowError, OSError, ValueError:
        return None


def chromium_timestamp_to_datetime(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None

    try:
        microseconds = int(value)
    except TypeError, ValueError:
        return None

    if microseconds <= 0:
        return None

    try:
        return CHROMIUM_EPOCH + timedelta(microseconds=microseconds)
    except OverflowError:
        return None


def normalize_cookie_key(name: str, domain: str, path: str) -> tuple[str, str, str]:
    normalized_domain = domain.lstrip(".").lower()
    return (name, normalized_domain, path)


def cookie_key_from_mapping(
    mapping: dict[str, Any], domain_key: str = "domain"
) -> tuple[str, str, str]:
    return normalize_cookie_key(
        str(mapping.get("name", "")),
        str(mapping.get(domain_key, "")),
        str(mapping.get("path", "")),
    )


def capture_browser_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        async () => {
          const readStorage = (storage) => {
            const items = [];
            for (let index = 0; index < storage.length; index += 1) {
              const key = storage.key(index);
              items.push({ key, value: storage.getItem(key) });
            }
            return items;
          };

          const indexedDbDatabases =
            window.indexedDB && typeof window.indexedDB.databases === "function"
              ? await window.indexedDB.databases()
              : null;

          return {
            capturedAtIso: new Date().toISOString(),
            url: window.location.href,
            origin: window.location.origin,
            title: document.title,
            referrer: document.referrer,
            documentCookie: document.cookie,
            localStorage: readStorage(window.localStorage),
            sessionStorage: readStorage(window.sessionStorage),
            indexedDbDatabases,
            userAgent: navigator.userAgent,
          };
        }
        """
    )


def read_sqlite_cookie_rows(cookie_db_path: Path) -> list[dict[str, Any]]:
    if not cookie_db_path.exists():
        return []

    query = """
        SELECT
            creation_utc,
            host_key,
            top_frame_site_key,
            name,
            value,
            encrypted_value,
            path,
            expires_utc,
            is_secure,
            is_httponly,
            last_access_utc,
            has_expires,
            is_persistent,
            priority,
            samesite,
            source_scheme,
            source_port,
            last_update_utc,
            source_type,
            has_cross_site_ancestor
        FROM cookies
        ORDER BY creation_utc ASC
    """

    connection = sqlite3.connect(cookie_db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in connection.execute(query).fetchall()]
    finally:
        connection.close()

    return rows


def build_enriched_sqlite_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched_rows: list[dict[str, Any]] = []

    for row in rows:
        created_at = chromium_timestamp_to_datetime(row.get("creation_utc"))
        last_accessed = chromium_timestamp_to_datetime(row.get("last_access_utc"))
        updated_at = chromium_timestamp_to_datetime(row.get("last_update_utc"))
        expires_at = chromium_timestamp_to_datetime(row.get("expires_utc"))

        enriched_row = dict(row)
        enriched_row["created"] = datetime_to_rfc1123(created_at)
        enriched_row["created_iso"] = created_at.isoformat() if created_at else None
        enriched_row["last_accessed"] = datetime_to_rfc1123(last_accessed)
        enriched_row["last_accessed_iso"] = (
            last_accessed.isoformat() if last_accessed else None
        )
        enriched_row["updated"] = datetime_to_rfc1123(updated_at)
        enriched_row["updated_iso"] = updated_at.isoformat() if updated_at else None
        enriched_row["expires_max_age"] = datetime_to_rfc1123(expires_at)
        enriched_row["expires_iso"] = expires_at.isoformat() if expires_at else None
        enriched_row["host_only"] = not str(row.get("host_key", "")).startswith(".")
        enriched_row["http_only"] = bool(row.get("is_httponly", 0))
        enriched_row["secure"] = bool(row.get("is_secure", 0))
        enriched_row["has_expires_flag"] = bool(row.get("has_expires", 0))
        enriched_row["is_persistent_flag"] = bool(row.get("is_persistent", 0))
        enriched_row["has_cross_site_ancestor_flag"] = bool(
            row.get("has_cross_site_ancestor", 0)
        )
        enriched_rows.append(enriched_row)

    return enriched_rows


def build_enriched_cookies(
    *,
    playwright_cookies: list[dict[str, Any]],
    cdp_cookies: list[dict[str, Any]],
    sqlite_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    playwright_by_key = {
        cookie_key_from_mapping(cookie): cookie for cookie in playwright_cookies
    }
    cdp_by_key = {cookie_key_from_mapping(cookie): cookie for cookie in cdp_cookies}
    sqlite_by_key = {
        cookie_key_from_mapping(cookie, domain_key="host_key"): cookie
        for cookie in sqlite_rows
    }

    ordered_keys: list[tuple[str, str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for collection, domain_key in (
        (sqlite_rows, "host_key"),
        (cdp_cookies, "domain"),
        (playwright_cookies, "domain"),
    ):
        for cookie in collection:
            key = cookie_key_from_mapping(cookie, domain_key=domain_key)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            ordered_keys.append(key)

    enriched: list[dict[str, Any]] = []
    for key in ordered_keys:
        sqlite_cookie = sqlite_by_key.get(key, {})
        cdp_cookie = cdp_by_key.get(key, {})
        playwright_cookie = playwright_by_key.get(key, {})

        created_at = chromium_timestamp_to_datetime(sqlite_cookie.get("creation_utc"))
        last_accessed = chromium_timestamp_to_datetime(
            sqlite_cookie.get("last_access_utc")
        )
        updated_at = chromium_timestamp_to_datetime(
            sqlite_cookie.get("last_update_utc")
        )
        expires_at = chromium_timestamp_to_datetime(sqlite_cookie.get("expires_utc"))
        if expires_at is None:
            expires_at = unix_seconds_to_datetime(cdp_cookie.get("expires"))
        if expires_at is None:
            expires_at = unix_seconds_to_datetime(playwright_cookie.get("expires"))

        domain = (
            str(cdp_cookie.get("domain", ""))
            or str(playwright_cookie.get("domain", ""))
            or str(sqlite_cookie.get("host_key", ""))
        )
        name = (
            str(cdp_cookie.get("name", ""))
            or str(playwright_cookie.get("name", ""))
            or str(sqlite_cookie.get("name", ""))
        )
        value = (
            str(cdp_cookie.get("value", ""))
            or str(playwright_cookie.get("value", ""))
            or str(sqlite_cookie.get("value", ""))
        )
        path = (
            str(cdp_cookie.get("path", ""))
            or str(playwright_cookie.get("path", ""))
            or str(sqlite_cookie.get("path", ""))
        )

        size = cdp_cookie.get("size")
        if size is None:
            size = len(name) + len(value)

        enriched.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "created": datetime_to_rfc1123(created_at),
                "created_iso": created_at.isoformat() if created_at else None,
                "expires_max_age": datetime_to_rfc1123(expires_at),
                "expires_iso": expires_at.isoformat() if expires_at else None,
                "expires_epoch_seconds": cdp_cookie.get("expires"),
                "host_only": (
                    sqlite_cookie.get("host_only")
                    if "host_only" in sqlite_cookie
                    else not domain.startswith(".")
                ),
                "http_only": bool(
                    cdp_cookie.get(
                        "httpOnly",
                        playwright_cookie.get(
                            "httpOnly", sqlite_cookie.get("is_httponly", 0)
                        ),
                    )
                ),
                "last_accessed": datetime_to_rfc1123(last_accessed),
                "last_accessed_iso": (
                    last_accessed.isoformat() if last_accessed else None
                ),
                "same_site": (
                    cdp_cookie.get("sameSite") or playwright_cookie.get("sameSite")
                ),
                "secure": bool(
                    cdp_cookie.get(
                        "secure",
                        playwright_cookie.get(
                            "secure", sqlite_cookie.get("is_secure", 0)
                        ),
                    )
                ),
                "session": bool(
                    cdp_cookie.get(
                        "session",
                        not bool(sqlite_cookie.get("has_expires", 0)),
                    )
                ),
                "size": size,
                "updated": datetime_to_rfc1123(updated_at),
                "updated_iso": updated_at.isoformat() if updated_at else None,
                "priority": cdp_cookie.get("priority"),
                "same_party": cdp_cookie.get("sameParty"),
                "source_scheme": cdp_cookie.get("sourceScheme"),
                "source_port": cdp_cookie.get("sourcePort"),
                "partition_key": cdp_cookie.get("partitionKey"),
                "partition_key_opaque": cdp_cookie.get("partitionKeyOpaque"),
                "top_frame_site_key": sqlite_cookie.get("top_frame_site_key"),
                "has_expires_flag": bool(sqlite_cookie.get("has_expires", 0))
                if sqlite_cookie
                else not bool(cdp_cookie.get("session", False)),
                "is_persistent_flag": bool(sqlite_cookie.get("is_persistent", 0))
                if sqlite_cookie
                else not bool(cdp_cookie.get("session", False)),
                "has_cross_site_ancestor_flag": bool(
                    sqlite_cookie.get("has_cross_site_ancestor", 0)
                )
                if sqlite_cookie
                else None,
            }
        )

    return enriched


def log_cookie(operator: str, index: int, cookie: dict[str, Any]) -> None:
    serialized = json.dumps(cookie, ensure_ascii=True, sort_keys=True)
    log_print(
        f"[{operator}] Cookie {index}: {serialized}",
        event="user_session.cookie",
        operator=operator,
        cookie_index=index,
        cookie_name=str(cookie.get("name", "")),
        cookie_value=str(cookie.get("value", "")),
        cookie_domain=str(cookie.get("domain", "")),
        cookie_path=str(cookie.get("path", "")),
        cookie_created=str(cookie.get("created", "")),
        cookie_expires=str(cookie.get("expires_max_age", "")),
        cookie_host_only=cookie.get("host_only"),
        cookie_http_only=cookie.get("http_only"),
        cookie_last_accessed=str(cookie.get("last_accessed", "")),
        cookie_same_site=str(cookie.get("same_site", "")),
        cookie_secure=cookie.get("secure"),
        cookie_size=cookie.get("size"),
        cookie_updated=str(cookie.get("updated", "")),
    )


def log_xhr_summary(operator: str, xhr_entries: list[dict[str, Any]]) -> None:
    for index, entry in enumerate(xhr_entries, start=1):
        log_print(
            (
                f"[{operator}] XHR {index}: "
                f"{entry.get('method')} {entry.get('url')} "
                f"status={entry.get('status')} "
                f"type={entry.get('resource_type')} "
                f"mime={entry.get('mime_type')}"
            ),
            event="user_session.xhr",
            operator=operator,
            xhr_index=index,
            method=entry.get("method"),
            url=entry.get("url"),
            status=entry.get("status"),
            resource_type=entry.get("resource_type"),
            mime_type=entry.get("mime_type"),
        )


def build_operator_paths(output_dir: Path, operator: str) -> dict[str, Path]:
    operator_slug = safe_slug(operator)
    artifact_dir = output_dir / operator_slug
    profile_dir = artifact_dir / "profile"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    return {
        "artifact_dir": artifact_dir,
        "profile_dir": profile_dir,
        "cookies_enriched": artifact_dir / "cookies_enriched.json",
        "cookies_playwright": artifact_dir / "cookies_playwright.json",
        "cookies_cdp": artifact_dir / "cookies_cdp.json",
        "cookies_sqlite": artifact_dir / "cookies_sqlite.json",
        "storage_state": artifact_dir / "storage_state.json",
        "web_storage": artifact_dir / "web_storage.json",
        "xhr": artifact_dir / "network_xhr.json",
        "session_summary": artifact_dir / "session_summary.json",
    }


def export_account_session(config: Config, output_dir: Path) -> SessionArtifacts:
    operator = config.email_user or "unknown"
    paths = build_operator_paths(output_dir, operator)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(paths["profile_dir"]),
            headless=config.headless,
        )

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.context.set_default_timeout(10000)

            page_cdp = context.new_cdp_session(page)
            browser_cdp = context.browser.new_browser_cdp_session()
            xhr_tracker = XHRTracker(page_cdp)
            xhr_tracker.enable()

            page.goto(config.url_application)

            login = Login(page)
            login.login(config.email_user, config.pin_user)
            page.wait_for_load_state("load")
            page.wait_for_timeout(DEFAULT_NETWORK_WAIT_MS)

            dashboard = Dashboard(page)
            profile_name = dashboard.get_profile_name()
            dashboard.assert_profile_name_is(profile_name)
            current_stock = dashboard.get_current_stock()
            page.wait_for_timeout(DEFAULT_NETWORK_WAIT_MS)

            playwright_cookies = context.cookies()
            cdp_cookies_payload = browser_cdp.send("Storage.getCookies")
            cdp_cookies = list(cdp_cookies_payload.get("cookies", []))
            storage_state = context.storage_state()
            web_storage = capture_browser_state(page)
            xhr_entries = xhr_tracker.export()
            session_summary = {
                "captured_at_iso": datetime.now(UTC).isoformat(),
                "operator": operator,
                "application_url": config.url_application,
                "final_url": page.url,
                "page_title": page.title(),
                "profile_name": profile_name,
                "current_stock": current_stock,
                "cookie_count_playwright": len(playwright_cookies),
                "cookie_count_cdp": len(cdp_cookies),
                "storage_state_origin_count": len(storage_state.get("origins", [])),
                "local_storage_item_count": len(web_storage.get("localStorage", [])),
                "session_storage_item_count": len(
                    web_storage.get("sessionStorage", [])
                ),
                "xhr_count": len(xhr_entries),
                "artifact_dir": paths["artifact_dir"].resolve(),
                "profile_dir": paths["profile_dir"].resolve(),
                "cookie_db_path": (
                    paths["profile_dir"] / "Default" / "Network" / "Cookies"
                ).resolve(),
            }
        finally:
            context.close()

    cookie_db_path = paths["profile_dir"] / "Default" / "Network" / "Cookies"
    sqlite_rows = build_enriched_sqlite_rows(read_sqlite_cookie_rows(cookie_db_path))
    enriched_cookies = build_enriched_cookies(
        playwright_cookies=playwright_cookies,
        cdp_cookies=cdp_cookies,
        sqlite_rows=sqlite_rows,
    )

    write_json(paths["cookies_playwright"], playwright_cookies)
    write_json(paths["cookies_cdp"], cdp_cookies_payload)
    write_json(paths["cookies_sqlite"], sqlite_rows)
    write_json(paths["cookies_enriched"], enriched_cookies)
    write_json(paths["storage_state"], storage_state)
    write_json(paths["web_storage"], web_storage)
    write_json(paths["xhr"], xhr_entries)
    write_json(paths["session_summary"], session_summary)

    log_print(
        f"[{operator}] Session captured with {len(enriched_cookies)} cookies and {len(xhr_entries)} XHR/fetch requests",
        event="user_session.captured",
        operator=operator,
        cookie_count=len(enriched_cookies),
        xhr_count=len(xhr_entries),
        artifact_dir=str(paths["artifact_dir"].resolve()),
        profile_dir=str(paths["profile_dir"].resolve()),
    )

    if not enriched_cookies:
        log_print(
            f"[{operator}] No cookies were captured for this account.",
            level="WARNING",
            event="user_session.empty",
            operator=operator,
        )

    for index, cookie in enumerate(enriched_cookies, start=1):
        log_cookie(operator, index, cookie)

    log_xhr_summary(operator, xhr_entries)

    logger.bind(
        event="user_session.artifacts_saved",
        operator=operator,
        cookie_count=len(enriched_cookies),
        xhr_count=len(xhr_entries),
        artifact_dir=str(paths["artifact_dir"].resolve()),
        profile_dir=str(paths["profile_dir"].resolve()),
        cookies_enriched_path=str(paths["cookies_enriched"].resolve()),
        cookies_playwright_path=str(paths["cookies_playwright"].resolve()),
        cookies_cdp_path=str(paths["cookies_cdp"].resolve()),
        cookies_sqlite_path=str(paths["cookies_sqlite"].resolve()),
        storage_state_path=str(paths["storage_state"].resolve()),
        web_storage_path=str(paths["web_storage"].resolve()),
        xhr_path=str(paths["xhr"].resolve()),
        session_summary_path=str(paths["session_summary"].resolve()),
    ).info("User session artifacts saved")

    return SessionArtifacts(
        operator=operator,
        artifact_dir=paths["artifact_dir"],
        profile_dir=paths["profile_dir"],
        cookie_count=len(enriched_cookies),
        xhr_count=len(xhr_entries),
    )
