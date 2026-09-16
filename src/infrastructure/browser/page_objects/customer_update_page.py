from __future__ import annotations

import re

from playwright.sync_api import Page

from src.application.models.customer_workflow import (
    CustomerUpdateData,
    indonesian_month_name,
)
from src.infrastructure.browser.page_objects.workflow_component import WorkflowComponent


class CustomerUpdatePage(WorkflowComponent):
    _HEADING = re.compile(r"^Lengkapi\s+Data\s+Pelanggan\s+di", re.IGNORECASE)

    def __init__(self, page: Page) -> None:
        super().__init__(page)

    def is_visible(self) -> bool:
        return (
            self.first_visible(
                (
                    self.page.get_by_test_id("btnSubmitUpdate"),
                    self.page.get_by_role("heading", name=self._HEADING),
                )
            )
            is not None
        )

    def fill_and_submit(self, customer: CustomerUpdateData) -> None:
        if not self.is_visible():
            raise RuntimeError("Customer update form is not visible")
        city = self.page.get_by_test_id("input-component")
        city.wait_for(state="visible", timeout=7000)
        city.fill(customer.city)
        self._select("Tgl", str(customer.birth_day), exact=True)
        self._select("Bln", indonesian_month_name(customer.birth_month))
        self._select("Thn", str(customer.birth_year))
        self.click_once(self.page.get_by_test_id("btnSubmitUpdate"))

    def _select(self, field: str, option: str, *, exact: bool = False) -> None:
        searchbox = self.page.get_by_role("searchbox", name=field)
        searchbox.wait_for(state="visible", timeout=7000)
        searchbox.click(timeout=7000)
        self.click_once(self.page.get_by_role("option", name=option, exact=exact))
