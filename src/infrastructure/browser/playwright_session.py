from types import TracebackType
from typing import Self

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from src.config import Config
from src.infrastructure.browser.page_objects.dashboard_page import Dashboard
from src.infrastructure.browser.page_objects.login_page import Login
from src.logging_utils import logger


class PlaywrightSession:
    """Manage the Playwright browser lifecycle and login bootstrap."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def __enter__(self) -> Self:
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.firefox.launch(headless=self.config.headless)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb

        try:
            if self.context:
                self.context.close()
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask the original failure.
            logger.bind(
                event="browser.session.cleanup_failed",
                resource="context",
                error_type=type(exc).__name__,
            ).debug("Failed to close browser context")

        try:
            if self.browser:
                self.browser.close()
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask the original failure.
            logger.bind(
                event="browser.session.cleanup_failed",
                resource="browser",
                error_type=type(exc).__name__,
            ).debug("Failed to close browser")

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask the original failure.
            logger.bind(
                event="browser.session.cleanup_failed",
                resource="playwright",
                error_type=type(exc).__name__,
            ).debug("Failed to stop Playwright")

    def require_page(self) -> Page:
        if not self.page:
            raise RuntimeError(
                "BrowserSession.page is not initialized. Use BrowserSession as a context manager."
            )
        return self.page

    def initialize_session(self) -> None:
        page = self.require_page()
        page.goto(self.config.url_application)

        login = Login(page)
        operator_id = getattr(self.config, "operator_id", "operator_01")
        logger.bind(
            event="operator.login.started",
            operator_id=operator_id,
        ).info("Operator login started")
        try:
            login.login(self.config.email_user, self.config.pin_user)
        except Exception:
            logger.bind(
                event="operator.login.failed",
                operator_id=operator_id,
            ).exception("Operator login failed")
            raise
        page.wait_for_load_state("load")

        dashboard = Dashboard(page)
        profile_name = dashboard.get_profile_name()
        dashboard.assert_profile_name_is(profile_name)
        dashboard.get_current_stock()
        logger.bind(
            event="operator.login.success",
            operator_id=operator_id,
        ).info("Operator login succeeded")


BrowserSession = PlaywrightSession

__all__ = ["BrowserSession", "PlaywrightSession"]
