from src.application.services.transaction_prechecks import TransactionPrechecksService
from src.infrastructure.browser.page_objects import (
    BasePage as NewBasePage,
    CekPenjualan as NewCekPenjualan,
    Dashboard as NewDashboard,
    Login as NewLogin,
    Penjualan as NewPenjualan,
)
from src.web.pages.base_page import BasePage
from src.web.pages.cek_penjualan import CekPenjualan
from src.web.pages.dashboard import Dashboard
from src.web.pages.login import Login
from src.web.pages.penjualan import Penjualan


class FakePage:
    def __init__(self) -> None:
        self.url = "https://app.test/dashboard"
        self.timeouts: list[int] = []

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.timeouts.append(timeout_ms)


class FakeLimiter:
    def __init__(self) -> None:
        self.skip_calls = 0

    def record_skip(self) -> None:
        self.skip_calls += 1


class FakeReporter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def skip_invalid_registered_nik(self, *args, **kwargs) -> None:
        self.calls.append(("skip_invalid_registered_nik", args, kwargs))

    def skip_needs_update(self, *args, **kwargs) -> None:
        self.calls.append(("skip_needs_update", args, kwargs))


class FakeDashboard:
    def __init__(self) -> None:
        self.dismiss_invalid_registered_nik_calls = 0
        self.reset_calls: list[dict] = []
        self.dismiss_perbarui_calls = 0

    def read_under_17_validation_if_present(self):
        return None

    def select_jenis_pelanggan_if_needed(self):
        return False

    def read_invalid_registered_nik_reason_if_present(self):
        return "NIK pelanggan yang didaftarkan tidak valid."

    def dismiss_invalid_registered_nik_modal(self):
        self.dismiss_invalid_registered_nik_calls += 1

    def read_unusual_transaction_reason_if_present(self):
        return None

    def dismiss_unusual_transaction_modal(self):
        raise AssertionError("should not be called")

    def read_cannot_transact_at_base_reason_if_present(self):
        return None

    def dismiss_cannot_transact_at_base_modal(self):
        raise AssertionError("should not be called")

    def detect_perbarui_data_pelanggan_if_needed(self):
        return False

    def attempt_continue_perbarui_data_pelanggan(self):
        return "not_present"

    def dismiss_perbarui_data_pelanggan_modal(self):
        self.dismiss_perbarui_calls += 1

    def read_pelanggan_tidak_terdaftar_reason_if_present(self):
        return None

    def dismiss_pelanggan_tidak_terdaftar_modal(self):
        raise AssertionError("should not be called")

    def reset_nik_input_or_return_to_dashboard(self, **kwargs):
        self.reset_calls.append(kwargs)


class FakePerbaruiDashboard(FakeDashboard):
    def __init__(self) -> None:
        super().__init__()
        self.invalid_reason_calls = 0

    def read_invalid_registered_nik_reason_if_present(self):
        self.invalid_reason_calls += 1
        return None

    def detect_perbarui_data_pelanggan_if_needed(self):
        return True

    def attempt_continue_perbarui_data_pelanggan(self):
        return "continued"


def test_legacy_page_object_modules_reexport_infrastructure_classes():
    assert BasePage is NewBasePage
    assert Dashboard is NewDashboard
    assert Login is NewLogin
    assert Penjualan is NewPenjualan
    assert CekPenjualan is NewCekPenjualan


def test_dashboard_legacy_wrapper_preserves_perbarui_close_reason():
    dashboard = Dashboard.__new__(Dashboard)
    state = {"dismissed": 0, "reset": 0}

    dashboard.detect_perbarui_data_pelanggan_if_needed = lambda detect_timeout=6000: True
    dashboard.attempt_continue_perbarui_data_pelanggan = lambda: "cannot_continue"
    dashboard.dismiss_perbarui_data_pelanggan_modal = (
        lambda: state.__setitem__("dismissed", state["dismissed"] + 1)
    )
    dashboard.reset_nik_input_or_return_to_dashboard = (
        lambda **kwargs: state.__setitem__("reset", state["reset"] + 1)
    )

    reason = dashboard.close_perbarui_data_pelanggan_if_needed()

    assert reason == "Perbarui Data Pelanggan cannot continue transaction; modal closed."
    assert state == {"dismissed": 1, "reset": 1}


def test_prechecks_service_interprets_invalid_registered_nik_modal():
    page = FakePage()
    reporter = FakeReporter()
    limiter = FakeLimiter()
    dashboard = FakeDashboard()
    service = TransactionPrechecksService(
        page=page,
        dashboard=dashboard,
        reporter=reporter,
        limiter=limiter,
        post_skip_cooldown_ms=300,
        max_kuota_timeout_ms=1500,
        zero_stock_timeout_ms=1500,
    )

    handled = service.handle_pre_checks("3174", "started-at")

    assert handled is True
    assert dashboard.dismiss_invalid_registered_nik_calls == 1
    assert dashboard.reset_calls == [
        {
            "reset_action_name": "resetting NIK input after warning modal",
            "reset_log": "Closed invalid registered-customer NIK modal; NIK input reset.",
            "dashboard_log": "Closed invalid registered-customer NIK modal; returned to dashboard.",
        }
    ]
    assert limiter.skip_calls == 1
    assert page.timeouts == [300]
    assert reporter.calls == [
        (
            "skip_invalid_registered_nik",
            ("3174", "started-at"),
            {"url": "https://app.test/dashboard"},
        )
    ]


def test_prechecks_service_allows_transaction_when_perbarui_can_continue():
    page = FakePage()
    reporter = FakeReporter()
    limiter = FakeLimiter()
    dashboard = FakePerbaruiDashboard()
    service = TransactionPrechecksService(
        page=page,
        dashboard=dashboard,
        reporter=reporter,
        limiter=limiter,
        post_skip_cooldown_ms=300,
        max_kuota_timeout_ms=1500,
        zero_stock_timeout_ms=1500,
    )

    handled = service.handle_pre_checks("3174", "started-at")

    assert handled is False
    assert dashboard.dismiss_perbarui_calls == 0
    assert dashboard.reset_calls == []
    assert limiter.skip_calls == 0
    assert page.timeouts == []
    assert reporter.calls == []
