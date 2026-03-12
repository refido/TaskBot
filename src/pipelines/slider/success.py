from __future__ import annotations

from playwright.sync_api import Locator, Page

from src.logging_utils import log_print
from src.pipelines.slider.types import SliderConfig


class SuccessDetector:
    """Detects CAPTCHA success."""

    _ROOT_HIDDEN_TIMEOUT_MS: int = 1500

    def __init__(self, config: SliderConfig) -> None:
        self.config = config

    def check_success(self, page: Page, root: Locator) -> bool:
        """Check if CAPTCHA was solved successfully."""
        if self._check_by_selector(page):
            return True
        if self._check_by_text(page):
            return True
        if self._check_root_hidden(root):
            return True
        return False

    def _check_by_selector(self, page: Page) -> bool:
        try:
            page.locator(self.config.success_selector).first.wait_for(
                timeout=self.config.max_wait_success_ms, state="visible"
            )
            return True
        except Exception as exc:
            log_print(f"[SuccessDetector] Selector not found: {exc}")
            return False

    def _check_by_text(self, page: Page) -> bool:
        try:
            page.get_by_text(self.config.success_text).first.wait_for(
                timeout=self.config.max_wait_success_ms, state="visible"
            )
            log_print(
                f"[SuccessDetector] SUCCESS via text '{self.config.success_text}'!"
            )
            return True
        except Exception as exc:
            log_print(f"[SuccessDetector] Text not found: {exc}")
            return False

    def _check_root_hidden(self, root: Locator) -> bool:
        try:
            root.wait_for(state="hidden", timeout=self._ROOT_HIDDEN_TIMEOUT_MS)
            return True
        except Exception as exc:
            log_print(f"[SuccessDetector] Root timeout: {exc}")
            return False
