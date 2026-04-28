import re

from playwright.sync_api import Page


_LOGIN_BUTTON_NAME = re.compile(r"^\s*masuk\s*$", re.I)
_EMAIL_INPUT_SELECTOR = (
    'div.mantine-TextInput-root:has(label:has-text("Email")) input'
)
_PIN_INPUT_SELECTOR = 'div.mantine-TextInput-root:has(label:has-text("PIN")) input'


class SessionExpiredError(RuntimeError):
    """Raised when the app forces the browser back to the login page."""


def is_login_page(page: Page, *, timeout_ms: int = 500) -> bool:
    """Best-effort detection for the app's login page."""
    try:
        if "login" in page.url.lower():
            return True
    except Exception:
        pass

    probes = (
        page.get_by_role("button", name=_LOGIN_BUTTON_NAME),
        page.locator(_EMAIL_INPUT_SELECTOR),
        page.locator(_PIN_INPUT_SELECTOR),
    )

    for probe in probes:
        try:
            if probe.is_visible(timeout=timeout_ms):
                return True
        except Exception:
            continue

    return False
