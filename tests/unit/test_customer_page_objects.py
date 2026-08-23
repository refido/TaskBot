from __future__ import annotations

from src.application.models.customer_workflow import CustomerUpdateData
from src.infrastructure.browser.page_objects.consent_page import ConsentPage
from src.infrastructure.browser.page_objects.customer_update_page import (
    CustomerUpdatePage,
)
from src.infrastructure.browser.page_objects.update_confirmation_modal import (
    UpdateConfirmationModal,
)
from src.infrastructure.browser.page_objects.update_required_modal import (
    UpdateRequiredModal,
)
from src.infrastructure.browser.page_objects.update_success_modal import (
    UpdateSuccessModal,
)


class FakeLocator:
    def __init__(self, name: object, page) -> None:
        self.name = name
        self.page = page
        self.clicks = 0
        self.fills = []

    def count(self) -> int:
        return 1

    def nth(self, _index: int):
        return self

    def is_visible(self, **_kwargs) -> bool:
        return True

    def wait_for(self, **_kwargs) -> None:
        return None

    def click(self, **_kwargs) -> None:
        self.clicks += 1

    def fill(self, value: str) -> None:
        self.fills.append(value)

    def filter(self, **_kwargs):
        return self

    def get_by_role(self, role: str, *, name=None, exact=None):
        return self.page.get_by_role(role, name=name, exact=exact)

    def get_by_text(self, text):
        return self.page.get_by_text(text)


class FakePage:
    def __init__(self) -> None:
        self.locators = {}
        self.role_queries = []

    def _get(self, key):
        return self.locators.setdefault(key, FakeLocator(key, self))

    def get_by_test_id(self, test_id: str):
        return self._get(("test_id", test_id))

    def get_by_role(self, role: str, *, name=None, exact=None):
        self.role_queries.append((role, name, exact))
        return self._get(("role", role, name, exact))

    def get_by_text(self, text):
        return self._get(("text", str(text)))


def test_customer_update_form_maps_fields_and_submits_exactly_once():
    page = FakePage()
    customer = CustomerUpdateData(
        nik="3573051108720003",
        city="KOTA MALANG",
        birth_day=11,
        birth_month=8,
        birth_year=1972,
    )

    CustomerUpdatePage(page).fill_and_submit(customer)

    assert page.get_by_test_id("input-component").fills == ["KOTA MALANG"]
    option_names = [
        name for role, name, _exact in page.role_queries if role == "option"
    ]
    assert option_names == ["11", "Agustus", "1972"]
    assert page.get_by_test_id("btnSubmitUpdate").clicks == 1
    assert not any(
        name == "YA, Perbarui DATA PELANGGAN"
        for _role, name, _exact in page.role_queries
    )


def test_update_confirmation_clicks_once_without_assuming_the_next_state():
    page = FakePage()

    UpdateConfirmationModal(page).confirm_once()

    button = page.get_by_role("button", name="YA, Perbarui DATA PELANGGAN", exact=True)
    assert button.clicks == 1
    assert not any(
        name == "KEMBALI KE HALAMAN UTAMA" for _role, name, _exact in page.role_queries
    )


def test_consent_clicks_selanjutnya_exactly_once():
    page = FakePage()

    ConsentPage(page).continue_()

    button = page.get_by_role("button", name="SELANJUTNYA", exact=True)
    assert button.clicks == 1


def test_update_required_opens_form_once_without_using_nanti_action():
    page = FakePage()

    UpdateRequiredModal(page).open_update_form()

    action = page.get_by_role("button", name=UpdateRequiredModal._ACTION, exact=None)
    assert action.clicks == 1
    assert not any(
        isinstance(name, str) and "NANTI" in name.upper()
        for _role, name, _exact in page.role_queries
    )


def test_update_success_returns_home_once():
    page = FakePage()

    UpdateSuccessModal(page).return_home()

    button = page.get_by_role("button", name="KEMBALI KE HALAMAN UTAMA", exact=True)
    assert button.clicks == 1
