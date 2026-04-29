from __future__ import annotations

from playwright.sync_api import Locator, Page

from src.logging_utils import log_print
from src.pipelines.slider.types import SliderConfig


class SuccessDetector:
    """Detects CAPTCHA success."""

    def __init__(self, config: SliderConfig) -> None:
        self.config = config

    def check_success(self, page: Page, root: Locator) -> bool:
        """Check if CAPTCHA was solved successfully."""
        signal = self._wait_for_any_success_signal(page, root)
        if signal:
            log_print(f"[SuccessDetector] SUCCESS via {signal}.")
            return True
        log_print("[SuccessDetector] No success signal detected before timeout.")
        return False

    def _wait_for_any_success_signal(self, page: Page, root: Locator) -> str | None:
        try:
            root_handle = root.element_handle(timeout=250)
        except Exception as exc:
            try:
                root.wait_for(state="hidden", timeout=250)
                return "root_hidden"
            except Exception:
                log_print(f"[SuccessDetector] Root handle unavailable: {exc}")
                return None

        try:
            result = page.wait_for_function(
                """
                ([root, successSelector, successText]) => {
                    const visible = (element) => {
                        if (!element || !element.isConnected) return false;
                        const style = window.getComputedStyle(element);
                        if (style.display === "none" || style.visibility === "hidden") {
                            return false;
                        }
                        const rect = element.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };

                    if (!visible(root)) return "root_hidden";

                    if (successSelector) {
                        const selectorMatch = document.querySelector(successSelector);
                        if (visible(selectorMatch)) return "selector";
                    }

                    if (
                        successText &&
                        document.body &&
                        document.body.innerText &&
                        document.body.innerText.includes(successText)
                    ) {
                        return "text";
                    }

                    return false;
                }
                """,
                arg=[
                    root_handle,
                    self.config.success_selector,
                    self.config.success_text,
                ],
                timeout=self.config.max_wait_success_ms,
                polling=self.config.success_poll_interval_ms,
            )
            value = result.json_value()
            return str(value) if value else None
        except Exception as exc:
            log_print(f"[SuccessDetector] Success wait timed out: {exc}")
            return None
