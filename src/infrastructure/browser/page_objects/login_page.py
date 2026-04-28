from playwright.sync_api import Page

from src.infrastructure.browser.page_objects.base_page import BasePage
from src.logging_utils import log_print


class Login(BasePage):
    def __init__(self, page: Page) -> None:
        super().__init__(page)
        self.email = page.locator(
            'div.mantine-TextInput-root:has(label:has-text("Email")) input'
        )
        self.pin = page.locator(
            'div.mantine-TextInput-root:has(label:has-text("PIN")) input'
        )
        self.sign_in = page.get_by_role("button", name="Masuk")

    def login(self, email_user: str, pin_user: str) -> None:
        self.fill_input(
            self.email,
            str(email_user),
            action_name="filling login email",
            allow_login_page=True,
        )
        log_print("Email filled", self._mask_email(email_user))

        self.fill_input(
            self.pin,
            str(pin_user),
            action_name="filling login PIN",
            allow_login_page=True,
        )
        log_print("PIN filled", "***")

        self.click_button_and_wait(
            self.sign_in,
            "MASUK",
            timeout_ms=10000,
            allow_login_page=True,
        )
        log_print("Masuk button clicked")

    @staticmethod
    def _mask_email(value: str) -> str:
        if "@" not in value:
            return "***"

        local, domain = value.split("@", 1)
        if not local:
            return f"***@{domain}"

        head = local[0]
        return f"{head}***@{domain}"
