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

    def skip_max_kuota(self, *args, **kwargs) -> None:
        self.calls.append(("skip_max_kuota", args, kwargs))

    def skip_out_of_stock(self, *args, **kwargs) -> None:
        self.calls.append(("skip_out_of_stock", args, kwargs))


class FakeDashboard:
    def __init__(self) -> None:
        self.dismiss_invalid_registered_nik_calls = 0
        self.reset_calls: list[dict] = []
        self.dismiss_perbarui_calls = 0
        self.transaction_ready_calls = 0
        self.modal_waits = 0
        self.form_or_modal_waits = 0

    def resolve_customer_entry(self):
        return "precheck_modal"

    def is_transaction_form_ready(self):
        self.transaction_ready_calls += 1
        return False

    def wait_for_precheck_modal(self):
        self.modal_waits += 1
        return "invalid_registered_nik"

    def wait_for_transaction_form_or_precheck_modal(self):
        self.form_or_modal_waits += 1
        return "precheck_modal"

    def get_visible_precheck_modal(self):
        return "invalid_registered_nik"

    def read_under_17_validation_if_present(self, detect_timeout=2000):
        return None

    def select_jenis_pelanggan_if_needed(self):
        return False

    def read_invalid_registered_nik_reason_if_present(self, detect_timeout=6000):
        return "NIK pelanggan yang didaftarkan tidak valid."

    def dismiss_invalid_registered_nik_modal(self):
        self.dismiss_invalid_registered_nik_calls += 1

    def read_unusual_transaction_reason_if_present(self, detect_timeout=6000):
        return None

    def dismiss_unusual_transaction_modal(self):
        raise AssertionError("should not be called")

    def read_cannot_transact_at_base_reason_if_present(self, detect_timeout=6000):
        return None

    def dismiss_cannot_transact_at_base_modal(self):
        raise AssertionError("should not be called")

    def detect_perbarui_data_pelanggan_if_needed(self, detect_timeout=6000):
        return False

    def attempt_continue_perbarui_data_pelanggan(self):
        return "not_present"

    def dismiss_perbarui_data_pelanggan_modal(self):
        self.dismiss_perbarui_calls += 1

    def read_pelanggan_tidak_terdaftar_reason_if_present(self, detect_timeout=6000):
        return None

    def dismiss_pelanggan_tidak_terdaftar_modal(self):
        raise AssertionError("should not be called")

    def reset_nik_input_or_return_to_dashboard(self, **kwargs):
        self.reset_calls.append(kwargs)


class FakePerbaruiDashboard(FakeDashboard):
    def __init__(self) -> None:
        super().__init__()
        self.invalid_reason_calls = 0

    def resolve_customer_entry(self):
        return "customer_type_selected"

    def wait_for_precheck_modal(self):
        self.modal_waits += 1
        return "perbarui"

    def wait_for_transaction_form_or_precheck_modal(self):
        self.form_or_modal_waits += 1
        return "precheck_modal"

    def get_visible_precheck_modal(self):
        return "perbarui"

    def read_invalid_registered_nik_reason_if_present(self, detect_timeout=6000):
        self.invalid_reason_calls += 1
        return None

    def detect_perbarui_data_pelanggan_if_needed(self):
        return True

    def attempt_continue_perbarui_data_pelanggan(self):
        return "continued"


class FakeReadyDashboard(FakeDashboard):
    def resolve_customer_entry(self):
        return "transaction_ready"

    def is_transaction_form_ready(self):
        raise AssertionError("success outcome should return before extra probing")

    def wait_for_precheck_modal(self):
        raise AssertionError("success outcome should not scan pre-check modals")

    def wait_for_transaction_form_or_precheck_modal(self):
        raise AssertionError("success outcome should not wait for form/modal race")


class FakeCustomerTypeReadyDashboard(FakeDashboard):
    def resolve_customer_entry(self):
        return "customer_type_selected"

    def wait_for_transaction_form_or_precheck_modal(self):
        self.form_or_modal_waits += 1
        return "transaction_ready"

    def wait_for_precheck_modal(self):
        raise AssertionError("form-ready outcome should not scan rare modals")


class FakePenjualanBlocker:
    def __init__(self, alert) -> None:
        self.alert = alert
        self.blocker_timeouts: list[int] = []
        self.ganti_calls = 0

    def read_transaction_blocker_alert(self, timeout: int):
        self.blocker_timeouts.append(timeout)
        return self.alert

    def ganti_pelanggan(self) -> None:
        self.ganti_calls += 1


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
    assert dashboard.form_or_modal_waits == 1
    assert dashboard.dismiss_perbarui_calls == 0
    assert dashboard.reset_calls == []
    assert limiter.skip_calls == 0
    assert page.timeouts == []
    assert reporter.calls == []


def test_prechecks_service_returns_immediately_when_transaction_ready():
    page = FakePage()
    reporter = FakeReporter()
    limiter = FakeLimiter()
    dashboard = FakeReadyDashboard()
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
    assert limiter.skip_calls == 0
    assert page.timeouts == []
    assert reporter.calls == []


def test_prechecks_service_returns_when_customer_type_reaches_form():
    page = FakePage()
    reporter = FakeReporter()
    limiter = FakeLimiter()
    dashboard = FakeCustomerTypeReadyDashboard()
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
    assert dashboard.form_or_modal_waits == 1
    assert limiter.skip_calls == 0
    assert page.timeouts == []
    assert reporter.calls == []


def test_prechecks_service_handles_max_kuota_from_combined_blocker():
    page = FakePage()
    reporter = FakeReporter()
    limiter = FakeLimiter()
    dashboard = FakeReadyDashboard()
    penjualan = FakePenjualanBlocker(("max_kuota", "Tidak dapat transaksi"))
    service = TransactionPrechecksService(
        page=page,
        dashboard=dashboard,
        reporter=reporter,
        limiter=limiter,
        post_skip_cooldown_ms=300,
        max_kuota_timeout_ms=1500,
        zero_stock_timeout_ms=1500,
    )

    outcome = service.check_transaction_blocker(
        penjualan, "3174", "started-at", "before cek pesanan"
    )

    assert outcome.should_skip is True
    assert outcome.stop_reason is None
    assert penjualan.blocker_timeouts == [1500]
    assert penjualan.ganti_calls == 1
    assert limiter.skip_calls == 1
    assert page.timeouts == [300]
    assert reporter.calls == [
        (
            "skip_max_kuota",
            ("3174", "started-at"),
            {
                "url": "https://app.test/dashboard",
                "reason": "Max kuota before cek pesanan",
            },
        )
    ]


def test_prechecks_service_handles_zero_stock_from_combined_blocker():
    page = FakePage()
    reporter = FakeReporter()
    limiter = FakeLimiter()
    dashboard = FakeReadyDashboard()
    alert_text = "Tidak dapat transaksi, stok tabung yang dapat dijual kosong."
    penjualan = FakePenjualanBlocker(("zero_stock", alert_text))
    service = TransactionPrechecksService(
        page=page,
        dashboard=dashboard,
        reporter=reporter,
        limiter=limiter,
        post_skip_cooldown_ms=300,
        max_kuota_timeout_ms=1500,
        zero_stock_timeout_ms=2000,
    )

    outcome = service.check_transaction_blocker(
        penjualan, "3174", "started-at", "after cek pesanan"
    )

    expected_reason = f"Sellable stock empty after cek pesanan: {alert_text}"
    assert outcome.should_skip is False
    assert outcome.stop_reason == expected_reason
    assert penjualan.blocker_timeouts == [2000]
    assert penjualan.ganti_calls == 0
    assert limiter.skip_calls == 1
    assert page.timeouts == [300]
    assert reporter.calls == [
        (
            "skip_out_of_stock",
            ("3174", "started-at"),
            {"url": "https://app.test/dashboard", "reason": expected_reason},
        )
    ]
