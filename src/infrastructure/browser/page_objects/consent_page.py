from __future__ import annotations

import re

from playwright.sync_api import Page

from src.infrastructure.browser.page_objects.workflow_component import WorkflowComponent


class ConsentPage(WorkflowComponent):
    _MARKER = re.compile(r"Pernyataan\s+Persetujuan", re.IGNORECASE)

    def __init__(self, page: Page) -> None:
        super().__init__(page)

    def is_visible(self) -> bool:
        return (
            self.first_visible(
                (
                    self.page.get_by_role("heading", name=self._MARKER),
                    self.page.get_by_text(self._MARKER),
                )
            )
            is not None
        )

    def continue_(self) -> None:
        self.click_once(self.page.get_by_role("button", name="SELANJUTNYA", exact=True))
