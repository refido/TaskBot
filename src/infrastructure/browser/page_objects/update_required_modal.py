from __future__ import annotations

import re

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.infrastructure.browser.page_objects.workflow_component import WorkflowComponent


class UpdateRequiredModal(WorkflowComponent):
    _MARKER = re.compile(r"Data\s+Pelanggan\s+belum\s+lengkap", re.IGNORECASE)
    _ACTION = re.compile(r"Update\s+Data\s+Pelanggan", re.IGNORECASE)

    def __init__(self, page: Page) -> None:
        super().__init__(page)

    def _dialog(self):
        return self.page.get_by_role("dialog").filter(has_text=self._MARKER)

    def is_visible(self) -> bool:
        return (
            self.first_visible(
                (
                    self._dialog(),
                    self.page.get_by_role("heading", name=self._MARKER),
                    self.page.get_by_text(self._MARKER),
                )
            )
            is not None
        )

    def open_update_form(self) -> None:
        if not self.is_visible():
            raise RuntimeError("Customer update-required modal is not visible")
        dialog = self._dialog()
        scoped = dialog if self.visible(dialog) else self.page
        action = self.first_visible(
            (
                scoped.get_by_role("button", name=self._ACTION),
                scoped.get_by_text(self._ACTION),
                self.page.get_by_role("button", name=self._ACTION),
                self.page.get_by_text(self._ACTION),
            )
        )
        if action is None:
            raise RuntimeError("Update Data Pelanggan action could not be found")
        self.click_once(action)
        try:
            self.page.get_by_test_id("btnSubmitUpdate").wait_for(
                state="visible", timeout=7000
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Customer update form did not become visible") from exc
