from playwright.sync_api import Locator, Page, expect

from src.logging_utils import log_print


class BasePage:
    """Shared helpers for POM classes."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def click_button_and_wait(
        self,
        button: Locator,
        expected_text: str,
        *,
        timeout_ms: int = 5000,
        load_state: str = "networkidle",
    ) -> None:
        expect(button).to_be_enabled(timeout=timeout_ms)
        text = button.inner_text()
        log_print("Clicking button name:", text)
        expect(button).to_contain_text(expected_text)
        button.click()
        self.page.wait_for_load_state(load_state)

    def fill_input(
        self, input_box: Locator, value: str, *, timeout_ms: int = 10000
    ) -> None:
        expect(input_box).to_be_visible(timeout=timeout_ms)
        input_box.click()
        input_box.fill("")
        input_box.type(value, delay=20)
