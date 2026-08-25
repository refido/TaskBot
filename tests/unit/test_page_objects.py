import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.application.models.customer_workflow import PrecheckAction
from src.application.services.transaction_prechecks import TransactionPrechecksService
from src.infrastructure.browser.page_objects import (
    BasePage as NewBasePage,
)
from src.infrastructure.browser.page_objects import (
    CekPenjualan as NewCekPenjualan,
)
from src.infrastructure.browser.page_objects import (
    Dashboard as NewDashboard,
)
from src.infrastructure.browser.page_objects import (
    Login as NewLogin,
)
from src.infrastructure.browser.page_objects import (
    Penjualan as NewPenjualan,
)
from src.infrastructure.browser.page_objects import dashboard_page as dashboard_module
from src.infrastructure.browser.page_objects import penjualan_page as penjualan_module
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
        self.workflow_calls: list[tuple[str, dict]] = []

    def record_workflow_event(self, nik: str, **kwargs) -> None:
        self.workflow_calls.append((nik, kwargs))

    def skip_invalid_registered_nik(self, *args, **kwargs) -> None:
        self.calls.append(("skip_invalid_registered_nik", args, kwargs))

    def skip_needs_update(self, *args, **kwargs) -> None:
        self.calls.append(("skip_needs_update", args, kwargs))

    def skip_max_kuota(self, *args, **kwargs) -> None:
        self.calls.append(("skip_max_kuota", args, kwargs))

    def skip_out_of_stock(self, *args, **kwargs) -> None:
        self.calls.append(("skip_out_of_stock", args, kwargs))

    def skip(self, *args, **kwargs) -> None:
        self.calls.append(("skip", args, kwargs))


class FakeDashboard:
    def __init__(self) -> None:
        self.dismiss_invalid_registered_nik_calls = 0
        self.reset_calls: list[dict] = []
        self.dismiss_perbarui_calls = 0
        self.transaction_ready_calls = 0
        self.modal_waits = 0
        self.dismiss_registration_request_limited_calls = 0

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

    def read_registration_request_limited_reason_if_present(self, detect_timeout=6000):
        return None

    def dismiss_registration_request_limited_modal(self):
        self.dismiss_registration_request_limited_calls += 1

    def reset_nik_input_or_return_to_dashboard(self, **kwargs):
        self.reset_calls.append(kwargs)


class FakePerbaruiDashboard(FakeDashboard):
    def __init__(self) -> None:
        super().__init__()
        self.invalid_reason_calls = 0
        self.resolve_calls = 0

    def resolve_customer_entry(self):
        self.resolve_calls += 1
        return (
            "customer_type_selected" if self.resolve_calls == 1 else "transaction_ready"
        )

    def get_visible_precheck_modal(self):
        return None

    def wait_for_precheck_modal(self):
        self.modal_waits += 1
        return "perbarui"

    def wait_for_transaction_form_or_precheck_modal(self):
        self.form_or_modal_waits += 1
        return "precheck_modal"

    def read_invalid_registered_nik_reason_if_present(self, detect_timeout=6000):
        self.invalid_reason_calls += 1

    def detect_perbarui_data_pelanggan_if_needed(self):
        return True

    def attempt_continue_perbarui_data_pelanggan(self):
        return "continued"


class FakeReadyDashboard(FakeDashboard):
    def resolve_customer_entry(self):
        return "transaction_ready"

    def get_visible_precheck_modal(self):
        return None

    def is_transaction_form_ready(self):
        raise AssertionError("success outcome should return before extra probing")

    def wait_for_precheck_modal(self):
        raise AssertionError("success outcome should not scan pre-check modals")

    def wait_for_transaction_form_or_precheck_modal(self):
        raise AssertionError("success outcome should not wait for form/modal race")


class FakeCustomerTypeReadyDashboard(FakeDashboard):
    def __init__(self) -> None:
        super().__init__()
        self.resolve_calls = 0

    def resolve_customer_entry(self):
        self.resolve_calls += 1
        return (
            "customer_type_selected" if self.resolve_calls == 1 else "transaction_ready"
        )

    def get_visible_precheck_modal(self):
        return None

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


@pytest.mark.parametrize(
    ("action", "expected_reason"),
    [
        ("close", "Perbarui Data Pelanggan closed; transaction skipped."),
        (
            "cannot_continue",
            "Perbarui Data Pelanggan cannot continue transaction; modal closed.",
        ),
    ],
)
def test_dashboard_legacy_wrapper_preserves_perbarui_close_reason(
    action, expected_reason
):
    dashboard = Dashboard.__new__(Dashboard)
    state = {"dismissed": 0, "reset": 0}

    dashboard.detect_perbarui_data_pelanggan_if_needed = lambda detect_timeout=6000: (
        True
    )
    dashboard.attempt_continue_perbarui_data_pelanggan = lambda: action
    dashboard.dismiss_perbarui_data_pelanggan_modal = lambda: state.__setitem__(
        "dismissed", state["dismissed"] + 1
    )
    dashboard.reset_nik_input_or_return_to_dashboard = lambda **kwargs: (
        state.__setitem__("reset", state["reset"] + 1)
    )

    reason = dashboard.close_perbarui_data_pelanggan_if_needed()

    assert reason == expected_reason
    assert state == {"dismissed": 1, "reset": 1}


def test_catat_penjualan_clicks_wait_for_ui_states_not_network_idle(monkeypatch):
    events = []

    class Locator:
        def __init__(self, *, initial_timeout=False) -> None:
            self.initial_timeout = initial_timeout
            self.wait_calls = 0
            self.first = self

        def wait_for(self, **_kwargs) -> None:
            self.wait_calls += 1
            if self.initial_timeout and self.wait_calls == 1:
                raise PlaywrightTimeoutError("not initially visible")

        def or_(self, _other):
            return self

        def is_visible(self, **_kwargs) -> bool:
            return True

        def press(self, key) -> None:
            events.append(("press", key))

    class Expectation:
        def to_be_visible(self, **_kwargs) -> None:
            return None

    dashboard = Dashboard.__new__(Dashboard)
    dashboard.nik_input = Locator(initial_timeout=True)
    dashboard.zero_stock_modal = Locator()
    dashboard.registration_request_limited_modal = object()
    dashboard.catat_penjualan_tile = Locator()
    dashboard.lanjutkan_penjualan_button = Locator()
    clicks = []
    dashboard.click_locator = lambda locator, **kwargs: (
        clicks.append(kwargs),
        events.append(("click", locator)),
    )
    dashboard.fill_input = lambda *_args, **_kwargs: events.append(("fill", None))
    monkeypatch.setattr(dashboard_module, "expect", lambda _locator: Expectation())

    outcome = dashboard.catat_penjualan("3573051108720003")

    assert outcome == "ready"
    assert [click["load_state"] for click in clicks] == [None, None]
    assert events[-3:] == [
        ("fill", None),
        ("press", "Escape"),
        ("click", dashboard.lanjutkan_penjualan_button),
    ]


def test_catat_penjualan_defers_existing_registration_limit_without_clicking():
    dashboard = Dashboard.__new__(Dashboard)
    dashboard.registration_request_limited_modal = object()
    dashboard._is_visible = lambda locator: (
        locator is dashboard.registration_request_limited_modal
    )
    dashboard.fill_input = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("NIK must not be filled behind a terminal modal")
    )

    assert (
        dashboard.catat_penjualan("3573051108720003") == "registration_request_limited"
    )


def test_terminal_blocker_modal_beats_stale_perbarui_modal():
    dashboard = Dashboard.__new__(Dashboard)
    dashboard.pelanggan_tidak_terdaftar_modal = object()
    dashboard.registration_request_limited_modal = object()
    dashboard.perbarui_data_pelanggan_modal = object()
    dashboard.perbarui_data_nib_pelanggan_modal = object()
    dashboard.invalid_registered_nik_modal = object()
    dashboard.cannot_transact_at_base_modal = object()
    dashboard.unusual_transaction_modal = object()
    visible = {
        dashboard.perbarui_data_pelanggan_modal,
        dashboard.perbarui_data_nib_pelanggan_modal,
        dashboard.invalid_registered_nik_modal,
    }
    dashboard._is_visible = lambda locator: locator in visible

    assert dashboard.get_visible_precheck_modal() == "invalid_registered_nik"


def test_registration_request_limit_beats_stale_customer_update_modal():
    dashboard = Dashboard.__new__(Dashboard)
    dashboard.pelanggan_tidak_terdaftar_modal = object()
    dashboard.registration_request_limited_modal = object()
    dashboard.perbarui_data_pelanggan_modal = object()
    dashboard.perbarui_data_nib_pelanggan_modal = object()
    dashboard.invalid_registered_nik_modal = object()
    dashboard.cannot_transact_at_base_modal = object()
    dashboard.unusual_transaction_modal = object()
    visible = {
        dashboard.registration_request_limited_modal,
        dashboard.perbarui_data_pelanggan_modal,
    }
    dashboard._is_visible = lambda locator: locator in visible

    assert dashboard.get_visible_precheck_modal() == "registration_request_limited"


def test_nib_reminder_marker_matches_supplied_text_only():
    nib_message = (
        "Pelanggan Usaha Mikro diwajibkan untuk melengkapi Nomor Induk Berusaha "
        "(NIB) dan memperbarui informasi jenis usaha paling lambat 31 Desember "
        "2026 atau sampai dengan ditetapkannya kriteria pelanggan LPG 3 Kg "
        "sebagai Usaha Mikro sesuai dengan ketentuan Pemerintah. Tekan "
        "\u201cLENGKAPI NIB\u201d untuk dapat melakukan transaksi."
    )

    assert dashboard_module._PERBARUI_DATA_NIB_PELANGGAN_MESSAGE.search(nib_message)
    assert not dashboard_module._PERBARUI_DATA_NIB_PELANGGAN_MESSAGE.search(
        "Data Pelanggan belum lengkap"
    )


def test_registration_request_limit_requires_revised_title_and_message():
    class SemanticLocator:
        def __init__(self, *, selector=None, role=None, name=None) -> None:
            self.selector = selector
            self.role = role
            self.name = name
            self.filters = []

        @property
        def first(self):
            return self

        def filter(self, **kwargs):
            self.filters.append(kwargs)
            return self

        def locator(self, selector, **_kwargs):
            return SemanticLocator(selector=selector)

        def get_by_role(self, role, **kwargs):
            return SemanticLocator(role=role, name=kwargs.get("name"))

        def get_by_text(self, *_args, **_kwargs):
            return SemanticLocator()

        def get_by_placeholder(self, *_args, **_kwargs):
            return SemanticLocator()

    dashboard = Dashboard(SemanticLocator())
    modal = dashboard.registration_request_limited_modal
    title = "Tidak Dapat Melanjutkan Pendaftaran Pelanggan"
    message = (
        "Terlalu banyak melakukan permintaan pendaftaran untuk NIK pelanggan "
        "ini. Silakan coba lagi di hari berikutnya."
    )

    descendants = [item["has"] for item in modal.filters if "has" in item]
    heading = next(item for item in descendants if item.selector.startswith("h1"))
    message_element = next(
        item for item in descendants if item.selector == "div.mantine-Text-root"
    )
    title_filter = next(
        item["has_text"] for item in heading.filters if "has_text" in item
    )
    message_filter = next(
        item["has_text"] for item in message_element.filters if "has_text" in item
    )
    close_button = dashboard.registration_request_limited_tutup
    close_filter = next(
        item["has_text"] for item in close_button.filters if "has_text" in item
    )

    assert modal.selector == "section"
    assert {item.get("visible") for item in modal.filters} == {None, True}
    assert title_filter.fullmatch(title)
    assert message_filter.fullmatch(message)
    assert close_button.selector == "button"
    assert close_filter.fullmatch("Tutup")
    assert not title_filter.fullmatch("Tidak Dapat Melanjutkan Transaksi")
    assert not message_filter.fullmatch("NIK pelanggan yang didaftarkan tidak valid.")
    assert not message_filter.fullmatch(f"{message} Pesan tambahan.")


def test_supplied_unhappy_flow_markers_use_semantic_locator_wiring():
    class RecordingLocator:
        def __init__(self, recorder) -> None:
            self.recorder = recorder

        @property
        def first(self):
            return self

        def filter(self, **kwargs):
            self.recorder["filters"].append(kwargs.get("has_text"))
            return self

        def locator(self, selector):
            self.recorder["selectors"].append(selector)
            return self

        def get_by_role(self, role, **kwargs):
            self.recorder["roles"].append((role, kwargs))
            return self

    class RecordingPage(RecordingLocator):
        def __init__(self) -> None:
            recorder = {"selectors": [], "filters": [], "roles": []}
            super().__init__(recorder)

        def get_by_text(self, *_args, **_kwargs):
            return self

        def get_by_placeholder(self, *_args, **_kwargs):
            return self

    page = RecordingPage()
    Dashboard(page)

    supplied_markers = [
        "NIK belum 17 tahun",
        "NIK pelanggan yang didaftarkan tidak valid.",
        "Pelanggan Tidak Dapat Transaksi di Pangkalan Ini",
        (
            "NIK pelanggan terindikasi transaksi tidak wajar di pangkalan lain "
            "dengan jarak tidak wajar dan waktu berdekatan."
        ),
        "Cocokan Gambar untuk Proses Keamanan Penjualan",
        (
            "Terlalu banyak melakukan permintaan pendaftaran untuk NIK pelanggan "
            "ini. Silakan coba lagi di hari berikutnya."
        ),
    ]
    regexes = [item for item in page.recorder["filters"] if hasattr(item, "search")]

    assert all(
        any(regex.search(marker) for regex in regexes) for marker in supplied_markers
    )
    assert all(
        "mantine-824czz" not in selector for selector in page.recorder["selectors"]
    )
    assert all(
        "styles_root__eZpRx" not in selector for selector in page.recorder["selectors"]
    )
    assert any(role == "dialog" for role, _kwargs in page.recorder["roles"])


def test_exact_monthly_purchase_warning_is_the_only_max_kuota_classification():
    warning = (
        "Tidak dapat transaksi karena telah melebihi batas kewajaran pembelian "
        "LPG 3 kg bulan ini."
    )

    assert penjualan_module.classify_transaction_blocker_text(warning) == "max_kuota"
    assert (
        penjualan_module.classify_transaction_blocker_text(
            "Tidak dapat transaksi karena telah melebihi batas kewajaran "
            "pembelian LPG\u00a03kg bulan ini"
        )
        == "max_kuota"
    )
    assert (
        penjualan_module.classify_transaction_blocker_text(
            "Tidak dapat transaksi karena alasan yang belum dikenal."
        )
        is None
    )
    assert (
        penjualan_module.classify_transaction_blocker_text(
            f"{warning} Informasi tambahan"
        )
        is None
    )


class FakeCustomerInformationLocator:
    def __init__(self, text: str = "", *, missing: bool = False) -> None:
        self.text = text
        self.missing = missing
        self.waits: list[tuple[str, int]] = []

    def wait_for(self, *, state: str, timeout: int) -> None:
        self.waits.append((state, timeout))
        if self.missing:
            raise PlaywrightTimeoutError("customer information not visible")

    def inner_text(self) -> str:
        return self.text


def test_penjualan_reads_customer_information_from_scoped_values():
    penjualan = Penjualan.__new__(Penjualan)
    penjualan.customer_information_heading = FakeCustomerInformationLocator(
        "Informasi Pelanggan"
    )
    penjualan.customer_name = FakeCustomerInformationLocator("  JOHN   DOE  ")
    penjualan.customer_type = FakeCustomerInformationLocator(" RUMAH\nTANGGA ")

    information = penjualan.read_customer_information(timeout=750)

    assert information == penjualan_module.CustomerInformation(
        nama_pengguna="JOHN DOE",
        jenis_pengguna="RUMAH TANGGA",
    )
    assert penjualan.customer_information_heading.waits == [("visible", 750)]
    assert penjualan.customer_name.waits == [("visible", 750)]
    assert penjualan.customer_type.waits == [("visible", 750)]


def test_penjualan_returns_empty_customer_information_when_section_is_missing():
    penjualan = Penjualan.__new__(Penjualan)
    penjualan.customer_information_heading = FakeCustomerInformationLocator(
        missing=True
    )
    penjualan.customer_name = FakeCustomerInformationLocator("SHOULD NOT BE READ")
    penjualan.customer_type = FakeCustomerInformationLocator("SHOULD NOT BE READ")

    information = penjualan.read_customer_information(timeout=250)

    assert information == penjualan_module.CustomerInformation()
    assert penjualan.customer_name.waits == []
    assert penjualan.customer_type.waits == []


def test_inline_transaction_blocker_is_a_known_customer_entry_outcome():
    dashboard = Dashboard.__new__(Dashboard)
    dashboard.nik_under_17_validation = object()
    dashboard.jenis_pelanggan_modal = object()
    dashboard.cek_pesanan_button = object()
    dashboard.transaction_blocker_alert = object()
    dashboard.get_visible_precheck_modal = lambda: None
    dashboard._has_visible_dialog = lambda: False
    dashboard._is_visible = lambda locator: (
        locator is dashboard.transaction_blocker_alert
    )

    assert dashboard.get_visible_customer_entry() == "transaction_blocked"


def test_visible_nib_reminder_is_not_classified_as_perbarui_customer_data():
    dashboard = Dashboard.__new__(Dashboard)
    dashboard.pelanggan_tidak_terdaftar_modal = object()
    dashboard.registration_request_limited_modal = object()
    dashboard.perbarui_data_pelanggan_modal = object()
    dashboard.perbarui_data_nib_pelanggan_modal = object()
    dashboard.invalid_registered_nik_modal = object()
    dashboard.cannot_transact_at_base_modal = object()
    dashboard.unusual_transaction_modal = object()
    dashboard._is_visible = lambda locator: (
        locator is dashboard.perbarui_data_nib_pelanggan_modal
    )

    assert dashboard.get_visible_precheck_modal() == "nib_reminder"


def test_registration_request_limit_close_uses_scoped_tutup_once():
    class Modal:
        def __init__(self) -> None:
            self.waits = []

        def wait_for(self, **kwargs) -> None:
            self.waits.append(kwargs)

    dashboard = Dashboard.__new__(Dashboard)
    dashboard.registration_request_limited_modal = Modal()
    dashboard.registration_request_limited_tutup = object()
    clicks = []
    dashboard.click_locator = lambda locator, **kwargs: clicks.append((locator, kwargs))

    dashboard.dismiss_registration_request_limited_modal()

    assert clicks == [
        (
            dashboard.registration_request_limited_tutup,
            {
                "action_name": "closing customer registration request-limit modal",
                "expected_text": "Tutup",
                "timeout_ms": 5000,
                "load_state": None,
            },
        )
    ]
    assert dashboard.registration_request_limited_modal.waits == [
        {"state": "hidden", "timeout": 7000}
    ]


def test_nib_reminder_continue_uses_renamed_locator_once():
    class Modal:
        def __init__(self) -> None:
            self.waits = []

        def wait_for(self, **kwargs) -> None:
            self.waits.append(kwargs)

    dashboard = Dashboard.__new__(Dashboard)
    dashboard.perbarui_data_nib_pelanggan_modal = Modal()
    dashboard.perbarui_data_nib_pelanggan_lanjut_nanti = object()
    clicks = []
    dashboard.click_locator = lambda locator, **kwargs: clicks.append((locator, kwargs))

    dashboard.continue_perbarui_data_nib_pelanggan()

    assert clicks == [
        (
            dashboard.perbarui_data_nib_pelanggan_lanjut_nanti,
            {
                "action_name": "continuing past Perbarui Data NIB Pelanggan modal",
                "timeout_ms": 5000,
                "load_state": None,
            },
        )
    ]
    assert dashboard.perbarui_data_nib_pelanggan_modal.waits == [
        {"state": "visible", "timeout": 5000},
    ]


def test_nib_live_path_instruments_detection_click_and_twenty_second_observation():
    class Modal:
        def wait_for(self, **_kwargs) -> None:
            return None

    dashboard = Dashboard.__new__(Dashboard)
    dashboard.perbarui_data_nib_pelanggan_modal = Modal()
    dashboard.perbarui_data_nib_pelanggan_lanjut_nanti = object()
    events: list[tuple] = []
    dashboard.click_locator = lambda locator, **kwargs: events.append(
        ("click", locator, kwargs)
    )
    dashboard._debug_interaction_checkpoint = lambda label, **_kwargs: events.append(
        ("checkpoint", label)
    )
    dashboard._debug_pause = lambda label: events.append(("pause", label))
    dashboard._debug_poll_interaction_states = lambda label: events.append(
        ("poll", label)
    )

    dashboard.continue_perbarui_data_nib_pelanggan()

    assert [event[:2] for event in events] == [
        ("checkpoint", "nib_modal_detected"),
        ("pause", "nib_modal_detected"),
        ("checkpoint", "nib_continue_later_before_click"),
        ("click", dashboard.perbarui_data_nib_pelanggan_lanjut_nanti),
        ("checkpoint", "nib_continue_later_after_click"),
        ("poll", "nib_continue_later_post_click_20s"),
    ]
    assert sum(event[0] == "click" for event in events) == 1


def test_nib_live_path_captures_after_state_even_when_click_raises():
    class Modal:
        def wait_for(self, **_kwargs) -> None:
            return None

    dashboard = Dashboard.__new__(Dashboard)
    dashboard.perbarui_data_nib_pelanggan_modal = Modal()
    dashboard.perbarui_data_nib_pelanggan_lanjut_nanti = object()
    labels: list[str] = []
    dashboard.click_locator = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("click failed")
    )
    dashboard._debug_interaction_checkpoint = lambda label, **_kwargs: labels.append(
        label
    )
    dashboard._debug_pause = lambda _label: None
    dashboard._debug_poll_interaction_states = lambda label: labels.append(label)

    with pytest.raises(RuntimeError, match="click failed"):
        dashboard.continue_perbarui_data_nib_pelanggan()

    assert labels[-2:] == [
        "nib_continue_later_after_click",
        "nib_continue_later_post_click_20s",
    ]


def test_customer_type_pause_is_after_confirmed_selection_and_before_continue(
    monkeypatch,
):
    class Expectation:
        def to_be_visible(self, **_kwargs) -> None:
            return None

    dashboard = Dashboard.__new__(Dashboard)
    dashboard.jenis_pelanggan_modal = object()
    choice = object()
    events: list[tuple] = []
    dashboard._find_customer_type_choice = lambda: ("Rumah Tangga", choice)
    dashboard._select_customer_type_with_confirmation = lambda option, locator: (
        events.append(("selected", option, locator))
    )
    dashboard._debug_interaction_checkpoint = lambda label: events.append(
        ("checkpoint", label)
    )
    dashboard._debug_pause = lambda label: events.append(("pause", label))
    dashboard._continue_jenis_pelanggan_with_confirmation = lambda option: (
        events.append(("continue", option))
    )
    monkeypatch.setattr(dashboard_module, "expect", lambda _locator: Expectation())

    dashboard.select_jenis_pelanggan()

    assert events == [
        ("selected", "Rumah Tangga", choice),
        ("checkpoint", "customer_type_radio_confirmed"),
        ("pause", "customer_type_radio_confirmed_before_continue"),
        ("continue", "Rumah Tangga"),
    ]


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

    assert handled is PrecheckAction.SKIP
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


def test_prechecks_service_resolves_again_after_customer_type():
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

    assert handled is PrecheckAction.CONTINUE
    assert dashboard.dismiss_perbarui_calls == 0
    assert dashboard.reset_calls == []
    assert limiter.skip_calls == 0
    assert page.timeouts == []
    assert reporter.calls == []
    assert [call[1]["event"] for call in reporter.workflow_calls] == [
        "customer_type_detected",
        "customer_type_selected",
    ]


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

    assert handled is PrecheckAction.CONTINUE
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

    assert handled is PrecheckAction.CONTINUE
    assert limiter.skip_calls == 0
    assert page.timeouts == []
    assert reporter.calls == []


def test_prechecks_service_handles_max_kuota_from_combined_blocker():
    page = FakePage()
    reporter = FakeReporter()
    limiter = FakeLimiter()
    dashboard = FakeReadyDashboard()
    alert_text = (
        "Tidak dapat transaksi karena telah melebihi batas kewajaran pembelian "
        "LPG 3 kg bulan ini."
    )
    penjualan = FakePenjualanBlocker(("max_kuota", alert_text))
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
        penjualan,
        "3174",
        "started-at",
        "before cek pesanan",
        nama_pengguna="JOHN DOE",
        jenis_pengguna="RUMAH TANGGA",
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
                "reason": f"Max kuota before cek pesanan: {alert_text}",
                "nama_pengguna": "JOHN DOE",
                "jenis_pengguna": "RUMAH TANGGA",
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
        penjualan,
        "3174",
        "started-at",
        "after cek pesanan",
        nama_pengguna="JOHN DOE",
        jenis_pengguna="RUMAH TANGGA",
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
            {
                "url": "https://app.test/dashboard",
                "reason": expected_reason,
                "nama_pengguna": "JOHN DOE",
                "jenis_pengguna": "RUMAH TANGGA",
            },
        )
    ]
