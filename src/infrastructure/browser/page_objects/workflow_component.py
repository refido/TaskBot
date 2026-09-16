from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page


class WorkflowComponent:
    def __init__(self, page: Page) -> None:
        self.page = page

    @staticmethod
    def visible(locator: Locator) -> bool:
        try:
            return locator.is_visible(timeout=150)
        except TypeError:
            try:
                return locator.is_visible()
            except PlaywrightError:
                return False
        except PlaywrightError:
            return False

    @classmethod
    def first_visible(cls, candidates: tuple[Locator, ...]) -> Locator | None:
        for candidate in candidates:
            try:
                count = candidate.count()
            except PlaywrightError:
                count = 1
            for index in range(count):
                current = candidate.nth(index) if count > 1 else candidate
                if cls.visible(current):
                    return current
        return None

    @staticmethod
    def click_once(locator: Locator, *, timeout: int = 7000) -> None:
        locator.wait_for(state="visible", timeout=timeout)
        locator.click(timeout=timeout)
