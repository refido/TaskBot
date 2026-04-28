from playwright.sync_api import Locator, Page, expect

from src.logging_utils import log_print
from src.web.session_state import SessionExpiredError, is_login_page


class BasePage:
    """Shared helpers for page objects."""

    _LOGIN_PAGE_CHECK_TIMEOUT_MS = 500

    def __init__(self, page: Page) -> None:
        self.page = page

    def click_locator(
        self,
        locator: Locator,
        *,
        action_name: str,
        expected_text: str | None = None,
        timeout_ms: int = 5000,
        load_state: str | None = "networkidle",
        allow_login_page: bool = False,
    ) -> None:
        self._raise_if_session_expired(
            action_name=action_name,
            allow_login_page=allow_login_page,
        )

        try:
            expect(locator).to_be_visible(timeout=timeout_ms)
            if expected_text:
                expect(locator).to_contain_text(expected_text)

            text = self._safe_inner_text(locator)
            if text:
                log_print("Clicking element name:", text)

            expect(locator).to_be_enabled(timeout=timeout_ms)
            locator.click(timeout=timeout_ms)
            if load_state:
                self.page.wait_for_load_state(load_state)
        except Exception as exc:
            self._raise_if_session_expired(
                action_name=action_name,
                allow_login_page=allow_login_page,
                original_exception=exc,
            )
            raise

        self._raise_if_session_expired(
            action_name=action_name,
            allow_login_page=allow_login_page,
        )

    def click_button_and_wait(
        self,
        button: Locator,
        expected_text: str,
        *,
        timeout_ms: int = 5000,
        load_state: str = "networkidle",
        allow_login_page: bool = False,
    ) -> None:
        self.click_locator(
            button,
            action_name=f"clicking '{expected_text}'",
            expected_text=expected_text,
            timeout_ms=timeout_ms,
            load_state=load_state,
            allow_login_page=allow_login_page,
        )

    def fill_input(
        self,
        input_box: Locator,
        value: str,
        *,
        timeout_ms: int = 10000,
        action_name: str = "filling input",
        allow_login_page: bool = False,
    ) -> None:
        self._raise_if_session_expired(
            action_name=action_name,
            allow_login_page=allow_login_page,
        )

        try:
            expect(input_box).to_be_visible(timeout=timeout_ms)
            input_box.click(timeout=timeout_ms)
            input_box.fill("")
            if value:
                input_box.type(value, delay=20)
        except Exception as exc:
            self._raise_if_session_expired(
                action_name=action_name,
                allow_login_page=allow_login_page,
                original_exception=exc,
            )
            raise

        self._raise_if_session_expired(
            action_name=action_name,
            allow_login_page=allow_login_page,
        )

    def _raise_if_session_expired(
        self,
        *,
        action_name: str,
        allow_login_page: bool,
        original_exception: Exception | None = None,
    ) -> None:
        if allow_login_page:
            return

        if not is_login_page(
            self.page, timeout_ms=self._LOGIN_PAGE_CHECK_TIMEOUT_MS
        ):
            return

        message = f"Session expired while {action_name}; app is on the login page."
        if original_exception is not None:
            raise SessionExpiredError(message) from original_exception
        raise SessionExpiredError(message)

    @staticmethod
    def _safe_inner_text(locator: Locator) -> str:
        try:
            return locator.inner_text().strip()
        except Exception:
            return ""
