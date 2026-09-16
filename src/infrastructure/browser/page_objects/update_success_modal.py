from __future__ import annotations

import re

from playwright.sync_api import Page

from src.infrastructure.browser.page_objects.workflow_component import WorkflowComponent


class UpdateSuccessModal(WorkflowComponent):
    _MARKER = re.compile(r"Data\s+Pelanggan\s+berhasil", re.IGNORECASE)

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

    def return_home(self) -> None:
        if not self.is_visible():
            raise RuntimeError("Customer update-success modal is not visible")
        self.click_once(
            self.page.get_by_role("button", name="KEMBALI KE HALAMAN UTAMA", exact=True)
        )
        try:
            self._dialog().wait_for(state="hidden", timeout=7000)
        except Exception as exc:
            if self.is_visible():
                raise RuntimeError("Update-success modal stayed visible") from exc
