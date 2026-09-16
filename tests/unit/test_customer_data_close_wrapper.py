"""Legacy wrapper contracts using real delegates and separate fake modal states."""

from types import SimpleNamespace

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.infrastructure.browser.page_objects import base_page, dashboard_page

CLOSED = "Perbarui Data Pelanggan closed; transaction skipped."


@pytest.fixture
def ui(monkeypatch):
    case = SimpleNamespace(
        customer=False, customer_continue=False, nib=None, nik_visible=True,
        nik="existing-nik", ready=False, home=False, clicks=[], fills=[], waits=[],
        errors={}, wait_errors={}, logs=[], diagnostics=[], elapsed=0,
        close_stays_visible=False, continue_stays_visible=False,
    )

    class Locator:
        def __init__(self, kind):
            self.kind = kind

        def is_visible(self, **_kwargs):
            return {
                "customer": case.customer,
                "customer_close": case.customer,
                "customer_continue": case.customer and case.customer_continue,
                "nib": case.nib is not None,
                "nib_continue": case.nib == "continue",
                "nib_close": case.nib == "close",
                "nik": case.nik_visible,
                "home": case.home,
                "navigation": True,
            }[self.kind]

        def wait_for(self, *, state, timeout):
            case.waits.append((self.kind, state, timeout))
            error = case.wait_errors.get((self.kind, state))
            if error:
                raise error
            if self.is_visible() != (state == "visible"):
                case.elapsed += timeout
                raise PlaywrightTimeoutError(f"{self.kind} did not become {state}")

        def to_be_visible(self, *, timeout):
            self.wait_for(state="visible", timeout=timeout)

        def to_be_enabled(self, **_kwargs):
            assert self.is_visible()

        def to_contain_text(self, text):
            assert text == "Tutup" and self.kind == "nib_close"

        def inner_text(self):
            return self.kind

        def click(self, **_kwargs):
            if self.kind != "nik":
                case.clicks.append(self.kind)
            error = case.errors.get(self.kind)
            if error:
                raise error
            if self.kind == "customer_close" and not case.close_stays_visible:
                case.customer = False
            elif self.kind == "customer_continue" and not case.continue_stays_visible:
                case.customer = False
                case.ready = True
            elif self.kind in {"nib_close", "nib_continue"}:
                case.nib = None
            elif self.kind == "navigation":
                case.home = True

        def fill(self, value):
            case.fills.append(value)
            case.nik = value

        def get_by_role(self, role, *, name):
            assert self.kind == "customer" and role == "button"
            assert name.search("NANTI SAJA, LANJUT PENJUALAN")
            return Locator("customer_continue")

        def locator(self, selector):
            assert self.kind == "nib" and selector == "button"
            return Locator("nib_close")

        def filter(self, **_kwargs):
            return self

        @property
        def first(self):
            return self

    dashboard = dashboard_page.Dashboard.__new__(dashboard_page.Dashboard)
    dashboard.page = SimpleNamespace(
        wait_for_timeout=lambda milliseconds: setattr(case, "elapsed", case.elapsed + milliseconds),
        get_by_role=lambda *_args, **_kwargs: Locator("navigation"),
    )
    for name, kind in {
        "perbarui_data_pelanggan_modal": "customer",
        "perbarui_data_pelanggan_tutup": "customer_close",
        "perbarui_data_nib_pelanggan_modal": "nib",
        "perbarui_data_nib_pelanggan_lanjut_nanti": "nib_continue",
        "perbarui_data_nib_pelanggan_tutup": "nib_close",
        "nik_input": "nik", "catat_penjualan_tile": "home",
    }.items():
        setattr(dashboard, name, Locator(kind))
    dashboard._debug_interaction_checkpoint = lambda label, **_kwargs: case.diagnostics.append(label)
    dashboard._debug_pause = lambda label: case.diagnostics.append(label)
    dashboard._debug_poll_interaction_states = lambda label: case.diagnostics.append(label)
    for module in (base_page, dashboard_page):
        monkeypatch.setattr(module, "expect", lambda locator: locator)
        monkeypatch.setattr(module, "log_print", lambda *args, **_kwargs: case.logs.append(args))
    monkeypatch.setattr(base_page, "is_login_page", lambda *_args, **_kwargs: False)
    case.dashboard = dashboard
    return case


@pytest.mark.parametrize("nib", [None, "continue", "close"])
def test_no_customer_modal_does_not_touch_nib(ui, nib):
    ui.nib = nib
    assert ui.dashboard.close_perbarui_data_pelanggan_if_needed(123) is None
    assert ui.clicks == []
    assert ui.fills == []
    assert ui.waits == [("customer", "visible", 123)]
    assert ui.nib == nib


def test_customer_only_dismisses_and_resets_without_nib_detection(ui):
    ui.customer = True
    assert ui.dashboard.close_perbarui_data_pelanggan_if_needed() == CLOSED
    assert ui.customer is False
    assert ui.nik == ""
    assert ui.clicks == ["customer_close"]
    assert not any(kind.startswith("nib") for kind, *_ in ui.waits)
    assert ("customer", "hidden", 7000) in ui.waits
    assert ("nik", "visible", 3000) in ui.waits


def test_customer_continue_preserves_nik_and_allows_transaction(ui):
    ui.customer = ui.customer_continue = True
    assert ui.dashboard.close_perbarui_data_pelanggan_if_needed() is None
    assert ui.clicks == ["customer_continue"]
    assert ui.ready is True
    assert ui.customer is False
    assert ui.nik == "existing-nik"
    assert ui.fills == []
    assert ("customer_continue", "visible", 2000) in ui.waits
    assert ("customer", "hidden", 7000) in ui.waits
    assert ui.diagnostics == []


@pytest.mark.parametrize("nib", ["continue", "close"])
def test_both_modal_states_only_close_customer_data(ui, nib):
    # Synthetic coexistence: selectors are independent; live co-occurrence is
    # unverified. This tests domain isolation, not a claim about the target UI.
    ui.customer = True
    ui.nib = nib
    assert ui.dashboard.close_perbarui_data_pelanggan_if_needed() == CLOSED
    assert ui.customer is False
    assert ui.nib == nib
    assert ui.clicks == ["customer_close"]
    assert ui.fills == [""]
    assert ui.diagnostics == []


def test_reset_falls_back_to_dashboard_when_nik_input_is_absent(ui):
    ui.customer = True
    ui.nik_visible = False
    assert ui.dashboard.close_perbarui_data_pelanggan_if_needed() == CLOSED
    assert ui.customer is False
    assert ui.home is True
    assert ui.clicks == ["customer_close", "navigation"]
    assert ui.fills == []


@pytest.mark.parametrize("error_type", [PlaywrightTimeoutError, PlaywrightError, RuntimeError])
def test_customer_dismiss_failure_propagates_without_reset(ui, error_type):
    ui.customer = True
    error = error_type("customer close failed")
    ui.errors["customer_close"] = error
    with pytest.raises(error_type) as caught:
        ui.dashboard.close_perbarui_data_pelanggan_if_needed()
    assert caught.value is error
    assert ui.customer is True
    assert ui.nik == "existing-nik"
    assert ui.fills == []


def test_customer_hidden_timeout_propagates_without_reset(ui):
    ui.customer = True
    ui.close_stays_visible = True
    with pytest.raises(PlaywrightTimeoutError, match="customer did not become hidden"):
        ui.dashboard.close_perbarui_data_pelanggan_if_needed()
    assert ui.clicks == ["customer_close"]
    assert ui.fills == []


def test_unexpected_detection_exception_propagates(ui):
    error = RuntimeError("detector failed")
    ui.wait_errors[("customer", "visible")] = error
    with pytest.raises(RuntimeError) as caught:
        ui.dashboard.close_perbarui_data_pelanggan_if_needed()
    assert caught.value is error
    assert ui.clicks == []


def test_unrelated_nib_failure_cannot_abort_customer_cleanup(ui):
    ui.customer = True
    ui.nib = "continue"
    error = RuntimeError("NIB action failed")
    ui.errors["nib_continue"] = error
    assert ui.dashboard.close_perbarui_data_pelanggan_if_needed() == CLOSED
    assert ui.customer is False
    assert ui.nib == "continue"
    assert ui.clicks == ["customer_close"]
    assert ui.fills == [""]
    assert ui.diagnostics == []


@pytest.mark.parametrize(
    ("error_type", "reason"),
    [
        (PlaywrightTimeoutError, CLOSED),
        (AssertionError, CLOSED),
        (PlaywrightError, "Perbarui Data Pelanggan cannot continue transaction; modal closed."),
        (RuntimeError, "Perbarui Data Pelanggan cannot continue transaction; modal closed."),
    ],
)
def test_customer_continue_failure_preserves_historical_reason_and_fallback(ui, error_type, reason):
    ui.customer = ui.customer_continue = True
    error = error_type("customer continue failed")
    ui.errors["customer_continue"] = error
    assert ui.dashboard.close_perbarui_data_pelanggan_if_needed() == reason
    assert ui.clicks == ["customer_continue", "customer_close"]
    assert ui.customer is False
    assert ui.ready is False
    assert ui.nik == ""
    assert ui.fills == [""]
    assert not any(kind.startswith("nib") for kind, *_ in ui.waits)


def test_customer_continue_requires_hidden_confirmation_before_success(ui):
    ui.customer = ui.customer_continue = True
    ui.continue_stays_visible = True
    assert ui.dashboard.close_perbarui_data_pelanggan_if_needed() == CLOSED
    assert ui.clicks == ["customer_continue", "customer_close"]
    assert ui.waits.count(("customer", "hidden", 7000)) == 2
    assert ui.customer is False
    assert ui.ready is False
    assert ui.nik == ""


def test_unexpected_reset_error_propagates_after_customer_dismiss(ui):
    ui.customer = True
    error = RuntimeError("reset failed")
    ui.wait_errors[("nik", "visible")] = error
    with pytest.raises(RuntimeError) as caught:
        ui.dashboard.close_perbarui_data_pelanggan_if_needed()
    assert caught.value is error
    assert ui.customer is False
    assert ui.clicks == ["customer_close"]
    assert ui.fills == []
