"""Read/dismiss primitives for locator-scoped warning modals.

Dashboard retains domain selectors, reason/log configuration and reset policy.
The supplied click operation preserves the owning page's session checks.
"""

from collections.abc import Callable

from playwright.sync_api import Locator, TimeoutError


class SimpleWarningModal:
    def __init__(self, modal: Locator) -> None:
        self.modal = modal

    def read_reason(
        self,
        *,
        log: Callable[..., None],
        detect_timeout: int,
        missing_log: str,
        title_locator=None,
        title_fallback: str = "",
        title_detect_log: str = "Detected modal title",
        message_locator=None,
        message_fallback: str = "",
        message_detect_log: str = "Detected modal message",
        missing_content_log: str = "Warning modal became visible without the expected title or message.",
    ) -> str | None:
        try:
            self.modal.wait_for(state="visible", timeout=detect_timeout)
        except TimeoutError:
            log(missing_log)
            return None

        modal_reason = message_fallback or title_fallback
        detected_content = False

        if message_locator is not None:
            try:
                message_locator.wait_for(state="visible", timeout=1500)
                modal_reason = message_locator.inner_text().strip() or modal_reason
                log(f"{message_detect_log}: {modal_reason}")
                detected_content = True
            except TimeoutError:
                pass

        if not detected_content and title_locator is not None:
            try:
                title_locator.wait_for(state="visible", timeout=1000)
                modal_title = title_locator.inner_text().strip()
                modal_reason = modal_title or modal_reason or title_fallback
                log(f"{title_detect_log}: {modal_title}")
                detected_content = True
            except TimeoutError:
                pass

        if not detected_content:
            log(missing_content_log)
            modal_reason = modal_reason or title_fallback or message_fallback

        return modal_reason

    def dismiss(
        self, *, close_button: Locator, click_locator: Callable[..., None]
    ) -> None:
        click_locator(
            close_button,
            action_name="closing warning modal",
            timeout_ms=5000,
            load_state=None,
        )
        self.modal.wait_for(state="hidden", timeout=7000)
