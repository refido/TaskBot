import re
from typing import Literal

from playwright.sync_api import Page, TimeoutError, expect

from src.infrastructure.browser.page_objects.base_page import BasePage
from src.logging_utils import log_print

_PERBARUI_DATA_PELANGGAN_CLOSED_REASON = (
    "Perbarui Data Pelanggan closed; transaction skipped."
)
_PERBARUI_DATA_PELANGGAN_CANNOT_CONTINUE_REASON = (
    "Perbarui Data Pelanggan cannot continue transaction; modal closed."
)
_NIK_UNDER_17_VALIDATION_TEXT = "NIK belum 17 tahun"
_INVALID_REGISTERED_NIK_MODAL_TITLE = "Tidak Dapat Melakukan Transaksi"
_INVALID_REGISTERED_NIK_MESSAGE = "NIK pelanggan yang didaftarkan tidak valid."
_CANNOT_TRANSACT_AT_BASE_TITLE = "Pelanggan Tidak Dapat Transaksi di Pangkalan Ini"
_UNUSUAL_TRANSACTION_MODAL_TITLE = "Tidak Dapat Melanjutkan Transaksi"
_UNUSUAL_TRANSACTION_MESSAGE = "NIK pelanggan terindikasi transaksi tidak wajar di pangkalan lain dengan jarak tidak wajar dan waktu berdekatan."
_FAILED_PUZZLE_MODAL_TITLE = "Cocokan Gambar untuk Proses Keamanan Penjualan"

PerbaruiDataPelangganAction = Literal[
    "not_present", "continued", "close", "cannot_continue"
]
CustomerEntryOutcome = Literal[
    "transaction_ready",
    "customer_type_selected",
    "under_17",
    "precheck_modal",
    "unknown",
]
PrecheckModalName = Literal[
    "not_registered",
    "perbarui",
    "invalid_registered_nik",
    "cannot_transact_at_base",
    "unusual_transaction",
]


class Dashboard(BasePage):
    def __init__(self, page: Page) -> None:
        super().__init__(page)
        self.profile_name = page.locator(
            "#__next .styles_wrapper__ASq0Q .mantine-Text-root"
        ).first
        self.current_stock = page.get_by_text("Tabung").first
        self.catat_penjualan_tile = page.get_by_text(
            "Catat Penjualan", exact=True
        ).first
        self.nik_input = page.get_by_placeholder(
            "Masukkan 16 digit NIK Pelanggan", exact=True
        )
        self.lanjutkan_penjualan_button = page.get_by_role(
            "button", name="LANJUTKAN PENJUALAN"
        )
        self.cek_pesanan_button = page.get_by_role("button", name="CEK PESANAN")

        self.jenis_pelanggan_modal = page.get_by_role("dialog").filter(
            has_text="Jenis Pelanggan"
        )
        self.jenis_pelanggan = self.jenis_pelanggan_modal.get_by_text(
            "Rumah Tangga", exact=True
        )
        self.jenis_pelanggan_usaha_mikro = (
            self.jenis_pelanggan_modal.locator("span.styles_label__6NaHc")
            .filter(has_text=re.compile(r"^\s*Usaha Mikro\s*$", re.I))
            .first
        )
        self.jenis_pelanggan_lanjutkan_penjualan_button = (
            self.jenis_pelanggan_modal.locator("button.styles_primary__k_AUJ")
            .filter(has_text=re.compile(r"^\s*LANJUTKAN PENJUALAN\s*$", re.IGNORECASE))
            .first
        )

        self.pelanggan_tidak_terdaftar_title = (
            page.locator(
                "section[role='dialog'] h5.mantine-Text-root.mantine-Title-root"
            )
            .filter(has_text=re.compile(r"^\s*Pelanggan Tidak Terdaftar\s*$", re.I))
            .first
        )
        self.pelanggan_tidak_terdaftar_modal = page.locator(
            "section[role='dialog']:has(h5.mantine-Text-root.mantine-Title-root:has-text('Pelanggan Tidak Terdaftar'))"
        ).first
        self.pelanggan_tidak_terdaftar_tutup = (
            self.pelanggan_tidak_terdaftar_modal.get_by_role("button")
            .filter(has_text=re.compile(r"^\s*tutup\s*$", re.I))
            .first
        )

        self.perbarui_data_pelanggan_modal = page.locator(
            'section[role="dialog"]:has(.mantine-Text-root:has-text("Perbarui Data Pelanggan"))'
        )
        self.perbarui_data_pelanggan_tutup = (
            self.perbarui_data_pelanggan_modal.get_by_role("button").filter(
                has_text=re.compile(r"^\s*tutup\s*$", re.I)
            )
        )
        self.perbarui_data_pelanggan_lanjut_nanti = (
            self.perbarui_data_pelanggan_modal.locator("button.styles_lightGreen__flYZ5")
            .filter(
                has_text=re.compile(
                    r"^\s*nanti saja,\s*lanjut transaksi\s*$", re.I
                )
            )
            .first
        )
        self.nik_under_17_validation = (
            page.locator("div.mantine-824czz")
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_NIK_UNDER_17_VALIDATION_TEXT)}\s*$", re.I
                )
            )
            .first
        )
        self.invalid_registered_nik_modal = page.locator(
            "section[role='dialog']:has(h6.mantine-Text-root.mantine-Title-root:has-text('Tidak Dapat Melakukan Transaksi')), "
            "section[role='dialog']:has(div.mantine-Text-root:has-text('NIK pelanggan yang didaftarkan tidak valid.'))"
        ).first
        self.invalid_registered_nik_modal_title = (
            self.invalid_registered_nik_modal.locator(
                "h6.mantine-Text-root.mantine-Title-root"
            )
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_INVALID_REGISTERED_NIK_MODAL_TITLE)}\s*$",
                    re.I,
                )
            )
            .first
        )
        self.invalid_registered_nik_modal_message = (
            self.invalid_registered_nik_modal.locator("div.mantine-Text-root")
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_INVALID_REGISTERED_NIK_MESSAGE)}\s*$", re.I
                )
            )
            .first
        )
        self.invalid_registered_nik_modal_tutup = (
            self.invalid_registered_nik_modal.locator("button.styles_root__eZpRx")
            .filter(has_text=re.compile(r"^\s*tutup\s*$", re.I))
            .first
        )

        self.cannot_transact_at_base_modal = page.locator(
            "section[role='dialog']:has(h6.mantine-Text-root.mantine-Title-root:has-text('Pelanggan Tidak Dapat Transaksi di Pangkalan Ini'))"
        ).first
        self.cannot_transact_at_base_modal_title = (
            self.cannot_transact_at_base_modal.locator(
                "h6.mantine-Text-root.mantine-Title-root"
            )
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_CANNOT_TRANSACT_AT_BASE_TITLE)}\s*$", re.I
                )
            )
            .first
        )
        self.cannot_transact_at_base_modal_tutup = (
            self.cannot_transact_at_base_modal.locator("button.styles_root__eZpRx")
            .filter(has_text=re.compile(r"^\s*tutup\s*$", re.I))
            .first
        )

        self.unusual_transaction_modal = page.locator(
            "section[role='dialog']:has(h6.mantine-Text-root.mantine-Title-root:has-text('Tidak Dapat Melanjutkan Transaksi')), "
            "section[role='dialog']:has(div.mantine-Text-root:has-text('NIK pelanggan terindikasi transaksi tidak wajar di pangkalan lain dengan jarak tidak wajar dan waktu berdekatan.'))"
        ).first
        self.unusual_transaction_modal_title = (
            self.unusual_transaction_modal.locator(
                "h6.mantine-Text-root.mantine-Title-root"
            )
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_UNUSUAL_TRANSACTION_MODAL_TITLE)}\s*$", re.I
                )
            )
            .first
        )
        self.unusual_transaction_modal_message = (
            self.unusual_transaction_modal.locator("div.mantine-Text-root")
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_UNUSUAL_TRANSACTION_MESSAGE)}\s*$", re.I
                )
            )
            .first
        )
        self.unusual_transaction_modal_tutup = (
            self.unusual_transaction_modal.locator("button.styles_root__eZpRx")
            .filter(has_text=re.compile(r"^\s*tutup\s*$", re.I))
            .first
        )
        self.failed_puzzle_modal = page.locator(
            "section[role='dialog']:has(h6.mantine-Text-root.mantine-Title-root.mantine-yzrvn2:has-text('Cocokan Gambar untuk Proses Keamanan Penjualan')), "
            "section[role='dialog']:has(h6.mantine-Text-root.mantine-Title-root:has-text('Cocokan Gambar untuk Proses Keamanan Penjualan'))"
        ).first
        self.failed_puzzle_modal_title = (
            self.failed_puzzle_modal.locator(
                "h6.mantine-Text-root.mantine-Title-root.mantine-yzrvn2, "
                "h6.mantine-Text-root.mantine-Title-root"
            )
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_FAILED_PUZZLE_MODAL_TITLE)}\s*$", re.I
                )
            )
            .first
        )

    def get_profile_name(self) -> str:
        expect(self.profile_name).to_be_visible(timeout=5000)
        name = self.profile_name.inner_text()
        log_print("Profile name retrieved:", name)
        return name

    def assert_profile_name_is(self, expected_name: str) -> None:
        expect(self.profile_name).to_be_visible(timeout=5000)
        expect(self.profile_name).to_have_text(expected_name, timeout=5000)

    def get_current_stock(self) -> str:
        expect(self.current_stock).to_be_visible(timeout=5000)
        stock = self.current_stock.inner_text()
        log_print("Current stock retrieved:", stock)
        return stock

    def catat_penjualan(self, nik: str) -> None:
        already_on_form = False
        try:
            self.nik_input.wait_for(state="visible", timeout=800)
            already_on_form = True
            log_print("NIK input already visible; skipping tile click")
        except Exception:
            pass

        if not already_on_form:
            self.click_locator(
                self.catat_penjualan_tile,
                action_name="opening Catat Penjualan",
                expected_text="Catat Penjualan",
                timeout_ms=5000,
            )
            expect(self.nik_input).to_be_visible(timeout=5000)

        self.fill_input(
            self.nik_input,
            str(nik),
            action_name=f"filling NIK {nik}",
        )
        log_print("NIK input filled with:", nik)

        self.click_locator(
            self.lanjutkan_penjualan_button,
            action_name=f"continuing sale for NIK {nik}",
            expected_text="LANJUTKAN PENJUALAN",
            timeout_ms=5000,
        )
        log_print("Lanjutkan Penjualan button clicked")

    def resolve_customer_entry(
        self, detect_timeout: int = 4000
    ) -> CustomerEntryOutcome:
        try:
            self._customer_entry_outcome_locator().first.wait_for(
                state="visible", timeout=detect_timeout
            )
        except TimeoutError:
            log_print("No customer-entry outcome detected yet; continuing checks.")
            return "unknown"

        if self._is_visible(self.nik_under_17_validation):
            return "under_17"

        if self._is_visible(self.jenis_pelanggan_modal):
            self.select_jenis_pelanggan()
            return "customer_type_selected"

        if self.is_transaction_form_ready(detect_timeout=100):
            return "transaction_ready"

        if self.get_visible_precheck_modal() is not None:
            return "precheck_modal"

        return "unknown"

    def is_transaction_form_ready(self, detect_timeout: int = 700) -> bool:
        try:
            self.cek_pesanan_button.wait_for(state="visible", timeout=detect_timeout)
        except TimeoutError:
            log_print("Transaction form not ready yet; checking blocking modals.")
            return False

        if self._has_visible_dialog():
            log_print(
                "Transaction form is visible with a blocking dialog; resolving modal first."
            )
            return False

        log_print("Transaction form ready; skipping rare pre-check modal scan.")
        return True

    def wait_for_precheck_modal(
        self, detect_timeout: int = 6000
    ) -> PrecheckModalName | None:
        try:
            self._precheck_modal_locator().first.wait_for(
                state="visible", timeout=detect_timeout
            )
        except TimeoutError:
            log_print("No known pre-check modal present; continuing transaction.")
            return None

        modal_name = self.get_visible_precheck_modal()
        if modal_name is None:
            log_print("A pre-check modal appeared but did not match known handlers.")
            return None

        log_print(f"Detected pre-check modal: {modal_name}")
        return modal_name

    def get_visible_precheck_modal(self) -> PrecheckModalName | None:
        for modal_name, modal in [
            ("not_registered", self.pelanggan_tidak_terdaftar_modal),
            ("perbarui", self.perbarui_data_pelanggan_modal),
            ("invalid_registered_nik", self.invalid_registered_nik_modal),
            ("cannot_transact_at_base", self.cannot_transact_at_base_modal),
            ("unusual_transaction", self.unusual_transaction_modal),
        ]:
            if self._is_visible(modal):
                return modal_name
        return None

    def select_jenis_pelanggan_if_needed(self, detect_timeout: int = 2000) -> bool:
        try:
            self.jenis_pelanggan_modal.wait_for(state="visible", timeout=detect_timeout)
        except TimeoutError as exc:
            log_print("Jenis Pelanggan modal not present; skipping.", exc)
            return False

        self.select_jenis_pelanggan()
        return True

    def select_jenis_pelanggan(self) -> None:
        selected_option_name = ""
        selection_errors: list[str] = []

        for option_name, radio_button in [
            ("Rumah Tangga", self.jenis_pelanggan),
            ("Usaha Mikro", self.jenis_pelanggan_usaha_mikro),
        ]:
            try:
                expect(radio_button).to_be_visible(timeout=10000)
                self.click_locator(
                    radio_button,
                    action_name=f"selecting jenis pelanggan '{option_name}'",
                    expected_text=option_name,
                    timeout_ms=10000,
                )
                log_print(f"Jenis Pelanggan radio_button clicked ({option_name})")
                selected_option_name = option_name
                break
            except Exception as exc:
                selection_errors.append(f"{option_name}: {exc}")
                log_print(
                    f"Jenis Pelanggan option '{option_name}' was not usable; trying next option.",
                    exc,
                )

        if not selected_option_name:
            raise RuntimeError(
                "Failed to select any Jenis Pelanggan option: "
                + " | ".join(selection_errors)
            )

        self.click_locator(
            self.jenis_pelanggan_lanjutkan_penjualan_button,
            action_name="continuing Jenis Pelanggan flow",
            expected_text="LANJUTKAN PENJUALAN",
            timeout_ms=10000,
        )
        log_print("Lanjutkan Penjualan button clicked")

    def read_pelanggan_tidak_terdaftar_reason_if_present(
        self, detect_timeout: int = 6000
    ) -> str | None:
        try:
            self.pelanggan_tidak_terdaftar_title.wait_for(
                state="visible", timeout=detect_timeout
            )
        except TimeoutError:
            log_print("Pelanggan Tidak Terdaftar modal not present; continuing.")
            return None

        modal_text = self.pelanggan_tidak_terdaftar_title.inner_text().strip()
        log_print(f"Detected pelanggan modal title: {modal_text}")
        self.pelanggan_tidak_terdaftar_modal.wait_for(state="visible", timeout=3000)
        return modal_text

    def dismiss_pelanggan_tidak_terdaftar_modal(self) -> None:
        self.click_locator(
            self.pelanggan_tidak_terdaftar_tutup,
            action_name="closing pelanggan tidak terdaftar modal",
            timeout_ms=5000,
            load_state=None,
        )
        try:
            self.pelanggan_tidak_terdaftar_modal.wait_for(state="hidden", timeout=3000)
        except TimeoutError:
            log_print(
                "Pelanggan Tidak Terdaftar modal stayed visible after click; continuing with recovery checks."
            )

    def read_under_17_validation_if_present(
        self, detect_timeout: int = 2000
    ) -> str | None:
        try:
            self.nik_under_17_validation.wait_for(
                state="visible", timeout=detect_timeout
            )
        except TimeoutError:
            log_print("Under-17 NIK validation message not present; continuing.")
            return None

        validation_text = self.nik_under_17_validation.inner_text().strip()
        if not validation_text:
            validation_text = _NIK_UNDER_17_VALIDATION_TEXT
        log_print(f"Detected NIK validation message: {validation_text}")
        return validation_text

    def read_failed_puzzle_modal_title_if_present(
        self, detect_timeout: int = 2500
    ) -> str | None:
        try:
            self.failed_puzzle_modal.wait_for(state="visible", timeout=detect_timeout)
        except TimeoutError:
            log_print("Failed puzzle modal not present; retry will not run.")
            return None

        modal_title = _FAILED_PUZZLE_MODAL_TITLE
        try:
            self.failed_puzzle_modal_title.wait_for(state="visible", timeout=1000)
            detected_title = self.failed_puzzle_modal_title.inner_text().strip()
            if detected_title:
                modal_title = detected_title
        except TimeoutError:
            pass

        log_print(f"Detected failed puzzle modal title: {modal_title}")
        return modal_title

    def read_invalid_registered_nik_reason_if_present(
        self, detect_timeout: int = 6000
    ) -> str | None:
        return self._read_simple_warning_modal_reason_if_present(
            modal=self.invalid_registered_nik_modal,
            detect_timeout=detect_timeout,
            missing_log="Invalid registered-customer NIK modal not present; continuing.",
            title_locator=self.invalid_registered_nik_modal_title,
            title_fallback=_INVALID_REGISTERED_NIK_MODAL_TITLE,
            title_detect_log="Detected invalid NIK modal title",
            message_locator=self.invalid_registered_nik_modal_message,
            message_fallback=_INVALID_REGISTERED_NIK_MESSAGE,
            message_detect_log="Detected invalid NIK modal message",
            missing_content_log="Invalid registered-customer NIK modal became visible without the expected title or message.",
        )

    def dismiss_invalid_registered_nik_modal(self) -> None:
        self._dismiss_simple_warning_modal(
            modal=self.invalid_registered_nik_modal,
            close_button=self.invalid_registered_nik_modal_tutup,
        )

    def read_unusual_transaction_reason_if_present(
        self, detect_timeout: int = 6000
    ) -> str | None:
        return self._read_simple_warning_modal_reason_if_present(
            modal=self.unusual_transaction_modal,
            detect_timeout=detect_timeout,
            missing_log="Unusual-transaction modal not present; continuing.",
            title_locator=self.unusual_transaction_modal_title,
            title_fallback=_UNUSUAL_TRANSACTION_MODAL_TITLE,
            title_detect_log="Detected unusual-transaction modal title",
            message_locator=self.unusual_transaction_modal_message,
            message_fallback=_UNUSUAL_TRANSACTION_MESSAGE,
            message_detect_log="Detected unusual-transaction modal message",
            missing_content_log="Unusual-transaction modal became visible without the expected title or message.",
        )

    def dismiss_unusual_transaction_modal(self) -> None:
        self._dismiss_simple_warning_modal(
            modal=self.unusual_transaction_modal,
            close_button=self.unusual_transaction_modal_tutup,
        )

    def read_cannot_transact_at_base_reason_if_present(
        self, detect_timeout: int = 6000
    ) -> str | None:
        return self._read_simple_warning_modal_reason_if_present(
            modal=self.cannot_transact_at_base_modal,
            detect_timeout=detect_timeout,
            missing_log="Base-restriction modal not present; continuing.",
            title_locator=self.cannot_transact_at_base_modal_title,
            title_fallback=_CANNOT_TRANSACT_AT_BASE_TITLE,
            title_detect_log="Detected base-restriction modal title",
            missing_content_log="Base-restriction modal became visible without the expected title.",
        )

    def dismiss_cannot_transact_at_base_modal(self) -> None:
        self._dismiss_simple_warning_modal(
            modal=self.cannot_transact_at_base_modal,
            close_button=self.cannot_transact_at_base_modal_tutup,
        )

    def detect_perbarui_data_pelanggan_if_needed(
        self, detect_timeout: int = 6000
    ) -> bool:
        try:
            self.perbarui_data_pelanggan_modal.wait_for(
                state="visible", timeout=detect_timeout
            )
            return True
        except TimeoutError:
            log_print("Perbarui Data Pelanggan modal not present; continuing.")
            return False

    def attempt_continue_perbarui_data_pelanggan(self) -> PerbaruiDataPelangganAction:
        if not self.detect_perbarui_data_pelanggan_if_needed():
            return "not_present"

        try:
            self.click_locator(
                self.perbarui_data_pelanggan_lanjut_nanti,
                action_name="continuing past Perbarui Data Pelanggan modal",
                timeout_ms=2000,
                load_state=None,
            )
            self.perbarui_data_pelanggan_modal.wait_for(state="hidden", timeout=7000)
            log_print(
                "Clicked 'NANTI SAJA, LANJUT TRANSAKSI' on 'Perbarui Data Pelanggan'; continuing transaction."
            )
            return "continued"
        except (TimeoutError, AssertionError):
            log_print(
                "Continue-transaction button on 'Perbarui Data Pelanggan' was not usable; closing modal instead."
            )
            return "close"
        except Exception as exc:
            log_print(
                "Failed to continue past 'Perbarui Data Pelanggan'; closing modal instead.",
                exc,
            )
            return "cannot_continue"

    def dismiss_perbarui_data_pelanggan_modal(self) -> None:
        self.click_locator(
            self.perbarui_data_pelanggan_tutup,
            action_name="closing Perbarui Data Pelanggan modal",
            timeout_ms=5000,
            load_state=None,
        )
        self.perbarui_data_pelanggan_modal.wait_for(state="hidden", timeout=7000)

    def reset_nik_input_or_return_to_dashboard(
        self,
        *,
        reset_action_name: str,
        reset_log: str,
        dashboard_log: str,
    ) -> None:
        try:
            self.nik_input.wait_for(state="visible", timeout=3000)
            self.fill_input(
                self.nik_input,
                "",
                action_name=reset_action_name,
            )
            log_print(reset_log)
        except TimeoutError:
            self.ensure_on_dashboard()
            log_print(dashboard_log)

    def ensure_on_dashboard(self) -> None:
        try:
            if self.catat_penjualan_tile.is_visible(timeout=800):
                return
        except Exception:
            pass

        for candidate in [
            self.page.get_by_role("button", name="KEMBALI KE HALAMAN UTAMA"),
            self.page.get_by_role("button", name="KEMBALI"),
            self.page.get_by_role("link", name="Beranda"),
            self.page.get_by_role("link", name="Dashboard"),
            self.page.get_by_role("button", name="TUTUP"),
        ]:
            try:
                candidate.click(timeout=700)
                break
            except Exception:
                continue

        expect(self.catat_penjualan_tile).to_be_visible(timeout=8000)

    def _read_simple_warning_modal_reason_if_present(
        self,
        *,
        modal,
        detect_timeout: int,
        missing_log: str,
        title_locator=None,
        title_fallback: str = "",
        title_detect_log: str = "Detected modal title",
        message_locator=None,
        message_fallback: str = "",
        message_detect_log: str = "Detected modal message",
        missing_content_log: str = "Warning modal became visible without the expected title or message.",
    ) -> str | None:
        try:
            modal.wait_for(state="visible", timeout=detect_timeout)
        except TimeoutError:
            log_print(missing_log)
            return None

        modal_reason = message_fallback or title_fallback
        detected_content = False

        if message_locator is not None:
            try:
                message_locator.wait_for(state="visible", timeout=1500)
                modal_reason = message_locator.inner_text().strip() or modal_reason
                log_print(f"{message_detect_log}: {modal_reason}")
                detected_content = True
            except TimeoutError:
                pass

        if not detected_content and title_locator is not None:
            try:
                title_locator.wait_for(state="visible", timeout=1000)
                modal_title = title_locator.inner_text().strip()
                modal_reason = modal_title or modal_reason or title_fallback
                log_print(f"{title_detect_log}: {modal_title}")
                detected_content = True
            except TimeoutError:
                pass

        if not detected_content:
            log_print(missing_content_log)
            modal_reason = modal_reason or title_fallback or message_fallback

        return modal_reason

    def _dismiss_simple_warning_modal(self, *, modal, close_button) -> None:
        self.click_locator(
            close_button,
            action_name="closing warning modal",
            timeout_ms=5000,
            load_state=None,
        )
        modal.wait_for(state="hidden", timeout=7000)

    def _customer_entry_outcome_locator(self):
        return (
            self.nik_under_17_validation.or_(self.jenis_pelanggan_modal)
            .or_(self.cek_pesanan_button)
            .or_(self._precheck_modal_locator())
        )

    def _precheck_modal_locator(self):
        return (
            self.pelanggan_tidak_terdaftar_modal.or_(
                self.perbarui_data_pelanggan_modal
            )
            .or_(self.invalid_registered_nik_modal)
            .or_(self.cannot_transact_at_base_modal)
            .or_(self.unusual_transaction_modal)
        )

    @staticmethod
    def _is_visible(locator) -> bool:
        try:
            return locator.is_visible(timeout=100)
        except TypeError:
            try:
                return locator.is_visible()
            except Exception:
                return False
        except Exception:
            return False

    def _has_visible_dialog(self) -> bool:
        try:
            return self.page.locator("[role='dialog']:visible").count() > 0
        except Exception:
            return False

    # Temporary compatibility wrappers for older callers.
    def close_pelanggan_tidak_terdaftar_if_needed(
        self, detect_timeout: int = 6000
    ) -> str | None:
        reason = self.read_pelanggan_tidak_terdaftar_reason_if_present(
            detect_timeout=detect_timeout
        )
        if not reason:
            return None

        self.dismiss_pelanggan_tidak_terdaftar_modal()
        self.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after pelanggan modal",
            reset_log="Closed 'Pelanggan Tidak Terdaftar'; NIK input reset.",
            dashboard_log="Closed 'Pelanggan Tidak Terdaftar'; returned to dashboard.",
        )
        return reason

    def detect_under_17_nik_if_needed(self, detect_timeout: int = 2000) -> str | None:
        reason = self.read_under_17_validation_if_present(detect_timeout=detect_timeout)
        if not reason:
            return None

        self.reset_nik_input_or_return_to_dashboard(
            reset_action_name="clearing NIK input after under-17 validation",
            reset_log="Cleared NIK input after under-17 validation message.",
            dashboard_log="Under-17 validation handled; returned to dashboard.",
        )
        return reason

    def detect_failed_puzzle_modal_if_needed(
        self, detect_timeout: int = 2500
    ) -> str | None:
        return self.read_failed_puzzle_modal_title_if_present(
            detect_timeout=detect_timeout
        )

    def close_invalid_registered_nik_if_needed(
        self, detect_timeout: int = 6000
    ) -> str | None:
        reason = self.read_invalid_registered_nik_reason_if_present(
            detect_timeout=detect_timeout
        )
        if not reason:
            return None

        self.dismiss_invalid_registered_nik_modal()
        self.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after warning modal",
            reset_log="Closed invalid registered-customer NIK modal; NIK input reset.",
            dashboard_log="Closed invalid registered-customer NIK modal; returned to dashboard.",
        )
        return reason

    def close_unusual_transaction_if_needed(
        self, detect_timeout: int = 6000
    ) -> str | None:
        reason = self.read_unusual_transaction_reason_if_present(
            detect_timeout=detect_timeout
        )
        if not reason:
            return None

        self.dismiss_unusual_transaction_modal()
        self.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after warning modal",
            reset_log="Closed unusual-transaction modal; NIK input reset.",
            dashboard_log="Closed unusual-transaction modal; returned to dashboard.",
        )
        return reason

    def close_cannot_transact_at_base_if_needed(
        self, detect_timeout: int = 6000
    ) -> str | None:
        reason = self.read_cannot_transact_at_base_reason_if_present(
            detect_timeout=detect_timeout
        )
        if not reason:
            return None

        self.dismiss_cannot_transact_at_base_modal()
        self.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after warning modal",
            reset_log="Closed base-restriction modal; NIK input reset.",
            dashboard_log="Closed base-restriction modal; returned to dashboard.",
        )
        return reason

    def close_perbarui_data_pelanggan_if_needed(
        self, detect_timeout: int = 6000
    ) -> str | None:
        if not self.detect_perbarui_data_pelanggan_if_needed(
            detect_timeout=detect_timeout
        ):
            return None

        action = self.attempt_continue_perbarui_data_pelanggan()
        if action == "continued":
            return None

        self.dismiss_perbarui_data_pelanggan_modal()
        self.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after Perbarui Data Pelanggan modal",
            reset_log="Closed 'Perbarui Data Pelanggan'; NIK input reset.",
            dashboard_log="Closed 'Perbarui Data Pelanggan'; returned to dashboard.",
        )
        if action == "cannot_continue":
            return _PERBARUI_DATA_PELANGGAN_CANNOT_CONTINUE_REASON
        return _PERBARUI_DATA_PELANGGAN_CLOSED_REASON
