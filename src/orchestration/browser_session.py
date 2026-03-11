from types import TracebackType
from typing import Optional, Type

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from src.config import Config
from src.web.pages.dashboard import Dashboard
from src.web.pages.login import Login


class BrowserSession:
    """Manages browser lifecycle and initialization."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def __enter__(self) -> "BrowserSession":
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.firefox.launch(headless=True)
        # self.browser = self.playwright.firefox.launch(headless=False, slow_mo=50)
        # self.browser = self.playwright.firefox.launch(headless=False)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        del exc_type, exc_val, exc_tb

        # Best-effort cleanup; do not raise from cleanup.
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass

        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass

    def require_page(self) -> Page:
        if not self.page:
            raise RuntimeError(
                "BrowserSession.page is not initialized. Use BrowserSession as a context manager."
            )
        return self.page

    def initialize_session(self) -> None:
        """Initialize browser session with login."""
        page = self.require_page()
        page.goto(self.config.url_application)

        login = Login(page)
        login.login(self.config.email_user, self.config.pin_user)
        page.wait_for_load_state("load")

        dashboard = Dashboard(page)
        profile_name = dashboard.get_profile_name()
        dashboard.assert_profile_name_is(profile_name)
        dashboard.get_current_stock()
