from __future__ import annotations

import re

from playwright.sync_api import Page

from src.infrastructure.browser.page_objects.workflow_component import WorkflowComponent


class UpdateConfirmationModal(WorkflowComponent):
    _MARKER = re.compile(r"Pastikan\s+semua\s+data\s+sudah", re.IGNORECASE)

    def __init__(self, page: Page) -> None:
        super().__init__(page)

    def _button(self):
        return self.page.get_by_role(
            "button", name="YA, Perbarui DATA PELANGGAN", exact=True
        )

    def is_visible(self) -> bool:
        return (
            self.first_visible(
                (
                    self.page.get_by_role("dialog").filter(has_text=self._MARKER),
                    self._button(),
                )
            )
            is not None
        )

    def confirm_once(self) -> None:
        if not self.is_visible():
            raise RuntimeError("Customer update-confirmation modal is not visible")
        self.click_once(self._button())
