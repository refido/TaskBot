import re
from collections.abc import Callable
from typing import Literal

from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    Locator,
    Page,
    TimeoutError,
    expect,
)

from src.infrastructure.browser.page_objects.base_page import BasePage
from src.infrastructure.browser.page_objects.penjualan_page import (
    TRANSACTION_BLOCKER_ALERT_RE,
)
from src.infrastructure.interaction_diagnostics import get_page_diagnostics
from src.logging_utils import log_print

_PERBARUI_DATA_PELANGGAN_CLOSED_REASON = (
    "Perbarui Data Pelanggan closed; transaction skipped."
)
_PERBARUI_DATA_PELANGGAN_CANNOT_CONTINUE_REASON = (
    "Perbarui Data Pelanggan cannot continue transaction; modal closed."
)
_PERBARUI_DATA_NIB_PELANGGAN_MESSAGE = re.compile(
    r"Pelanggan\s+Usaha\s+Mikro\s+diwajibkan\s+untuk\s+melengkapi\s+"
    r"Nomor\s+Induk\s+Berusaha\s*\(NIB\).*?"
    r'Tekan\s+["\u201c]LENGKAPI\s+NIB["\u201d]\s+untuk\s+dapat\s+melakukan\s+transaksi',
    re.IGNORECASE | re.DOTALL,
)
_NIB_REMINDER_TITLE = re.compile(
    r"^\s*Segera\s+Lengkapi\s+NIB\s*$",
    re.IGNORECASE,
)
_NIB_CONTINUE_LATER_BUTTON = re.compile(
    r"^\s*nanti\s+saja,\s*lanjut\s+(?:penjualan|transaksi)\s*$",
    re.IGNORECASE,
)
_NIB_TUTUP_BUTTON = re.compile(
    r"^\s*tutup\s*$",
    re.IGNORECASE,
)
_NIK_UNDER_17_VALIDATION_TEXT = "NIK belum 17 tahun"
_INVALID_REGISTERED_NIK_MODAL_TITLE = "Tidak Dapat Melakukan Transaksi"
_INVALID_REGISTERED_NIK_MESSAGE = "NIK pelanggan yang didaftarkan tidak valid."
_CANNOT_TRANSACT_AT_BASE_TITLE = "Pelanggan Tidak Dapat Transaksi di Pangkalan Ini"
_UNUSUAL_TRANSACTION_MODAL_TITLE = "Tidak Dapat Melanjutkan Transaksi"
_UNUSUAL_TRANSACTION_MESSAGE = "NIK pelanggan terindikasi transaksi tidak wajar di pangkalan lain dengan jarak tidak wajar dan waktu berdekatan."
_FAILED_PUZZLE_MODAL_TITLE = "Cocokan Gambar untuk Proses Keamanan Penjualan"
_REGISTRATION_REQUEST_LIMITED_MODAL_TITLE_TEXT = (
    "Tidak Dapat Melanjutkan Pendaftaran Pelanggan"
)
_REGISTRATION_REQUEST_LIMITED_MODAL_TITLE = re.compile(
    r"^\s*Tidak\s+Dapat\s+Melanjutkan\s+Pendaftaran\s+Pelanggan\s*$",
    re.IGNORECASE,
)
_REGISTRATION_REQUEST_LIMITED_MESSAGE_TEXT = (
    "Terlalu banyak melakukan permintaan pendaftaran untuk NIK pelanggan ini. "
    "Silakan coba lagi di hari berikutnya."
)
_REGISTRATION_REQUEST_LIMITED_MESSAGE_EXACT = re.compile(
    r"^\s*Terlalu\s+banyak\s+melakukan\s+permintaan\s+pendaftaran\s+untuk\s+"
    r"NIK\s+pelanggan\s+ini\.\s+Silakan\s+coba\s+lagi\s+di\s+hari\s+"
    r"berikutnya\.\s*$",
    re.IGNORECASE,
)
_REGISTRATION_REQUEST_LIMITED_TUTUP = re.compile(
    r"^\s*Tutup\s*$",
    re.IGNORECASE,
)

_ZERO_STOCK_CONFIRM_ATTEMPTS = 3
_ZERO_STOCK_RETRY_DELAY_MS = 2500

_CUSTOMER_TYPE_CONSENT_MARKER = re.compile(
    r"Pernyataan\s+Persetujuan",
    re.IGNORECASE,
)

_CUSTOMER_TYPE_UPDATE_REQUIRED_MARKER = re.compile(
    r"Data\s+Pelanggan\s+belum\s+lengkap",
    re.IGNORECASE,
)

_CUSTOMER_TYPE_SELECTION_ATTEMPTS = 3
_CUSTOMER_TYPE_SELECTION_VERIFY_MS = 5000

# The target application can take several seconds to react after a click.
# These waits are post-condition waits, not blind sleeps.
_CUSTOMER_TYPE_CONTINUE_ATTEMPTS = 3
_CUSTOMER_TYPE_CONTINUE_RESULT_TIMEOUT_MS = 20000
_CUSTOMER_TYPE_CONTINUE_POLL_MS = 250

_NIB_CONTINUE_ATTEMPTS = 2
_NIB_POST_CLICK_TIMEOUT_MS = 20000
_NIB_POST_CLICK_POLL_MS = 250
_NIB_TUTUP_CLICK_ATTEMPTS = 3

PerbaruiDataPelangganAction = Literal[
    "not_present", "continued", "close", "cannot_continue"
]

CatatPenjualanOutcome = Literal[
    "ready",
    "zero_stock",
    "registration_request_limited",
]

CustomerEntryOutcome = Literal[
    "transaction_ready",
    "transaction_blocked",
    "customer_type",
    "customer_type_selected",
    "under_17",
    "precheck_modal",
    "unknown",
]
PrecheckModalName = Literal[
    "not_registered",
    "registration_request_limited",
    "nib_reminder",
    "perbarui",
    "invalid_registered_nik",
    "cannot_transact_at_base",
    "unusual_transaction",
]
PostCustomerEntryOutcome = Literal["transaction_ready", "precheck_modal", "unknown"]


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

        self.zero_stock_modal = page.locator(
            "section[role='dialog']:has("
            "h6.mantine-Text-root.mantine-Title-root:"
            "has-text('Stok Tabung Kosong'))"
        ).first

        self.zero_stock_modal_title = (
            self.zero_stock_modal.locator("h6.mantine-Text-root.mantine-Title-root")
            .filter(
                has_text=re.compile(
                    r"^\s*Stok Tabung Kosong\s*$",
                    re.IGNORECASE,
                )
            )
            .first
        )

        self.zero_stock_modal_tutup = (
            self.zero_stock_modal.get_by_role("button")
            .filter(
                has_text=re.compile(
                    r"^\s*TUTUP\s*$",
                    re.IGNORECASE,
                )
            )
            .first
        )

        self.nik_input = page.get_by_placeholder(
            "Masukkan 16 digit NIK Pelanggan", exact=True
        )

        self.lanjutkan_penjualan_button = page.get_by_role(
            "button", name="LANJUTKAN PENJUALAN"
        )

        self.cek_pesanan_button = page.get_by_role("button", name="CEK PESANAN")

        self.transaction_blocker_alert = (
            page.locator(
                ".styles_alertInfo__WvEN4 .styles_content__fqQml > "
                "span:nth-child(1):visible, div.mantine-Text-root:visible"
            )
            .filter(has_text=TRANSACTION_BLOCKER_ALERT_RE)
            .first
        )

        jenis_pelanggan_marker = re.compile(
            r"Jenis\s+Pelanggan|"
            r"Pelanggan\s+Terdaftar|"
            r"pilihan\s+jenis\s+pelanggan",
            re.IGNORECASE,
        )

        # Mantine portals may leave stale/aria-hidden dialog copies in the DOM.
        # Scope all interactions to the currently visible modal section.
        self.jenis_pelanggan_modal = (
            page.locator("section")
            .filter(has_text=jenis_pelanggan_marker)
            .filter(visible=True)
            .first
        )

        self.jenis_pelanggan_lanjutkan_penjualan_button = (
            self.jenis_pelanggan_modal.locator("button")
            .filter(
                has_text=re.compile(
                    r"^\s*LANJUTKAN\s+PENJUALAN\s*$",
                    re.IGNORECASE,
                )
            )
            .filter(visible=True)
            .first
        )

        self.pelanggan_tidak_terdaftar_title = (
            page.locator(
                "section[role='dialog'] h5.mantine-Text-root.mantine-Title-root"
            )
            .filter(
                has_text=re.compile(r"^\s*Pelanggan Tidak Terdaftar\s*$", re.IGNORECASE)
            )
            .first
        )

        self.pelanggan_tidak_terdaftar_modal = page.locator(
            "section[role='dialog']:has(h5.mantine-Text-root.mantine-Title-root:has-text('Pelanggan Tidak Terdaftar'))"
        ).first

        self.pelanggan_tidak_terdaftar_tutup = (
            self.pelanggan_tidak_terdaftar_modal.get_by_role("button")
            .filter(has_text=re.compile(r"^\s*tutup\s*$", re.IGNORECASE))
            .first
        )

        registration_request_limited_heading = (
            page.locator("h1, h2, h3, h4, h5, h6")
            .filter(has_text=_REGISTRATION_REQUEST_LIMITED_MODAL_TITLE)
            .filter(visible=True)
        )
        registration_request_limited_message = (
            page.locator("div.mantine-Text-root")
            .filter(has_text=_REGISTRATION_REQUEST_LIMITED_MESSAGE_EXACT)
            .filter(visible=True)
        )

        # The deployed Mantine portal can be visually displayed beneath an
        # aria-hidden wrapper. Use the visible modal section plus exact semantic
        # descendants instead of accessibility roles, which exclude that live
        # subtree. Visibility filters prevent stale portal copies from winning.
        self.registration_request_limited_modal = (
            page.locator("section")
            .filter(has=registration_request_limited_heading)
            .filter(has=registration_request_limited_message)
            .filter(visible=True)
            .first
        )

        self.registration_request_limited_title = (
            self.registration_request_limited_modal.locator("h1, h2, h3, h4, h5, h6")
            .filter(has_text=_REGISTRATION_REQUEST_LIMITED_MODAL_TITLE)
            .filter(visible=True)
            .first
        )

        self.registration_request_limited_message = (
            self.registration_request_limited_modal.locator("div.mantine-Text-root")
            .filter(has_text=_REGISTRATION_REQUEST_LIMITED_MESSAGE_EXACT)
            .filter(visible=True)
            .first
        )

        self.registration_request_limited_tutup = (
            self.registration_request_limited_modal.locator("button")
            .filter(has_text=_REGISTRATION_REQUEST_LIMITED_TUTUP)
            .filter(visible=True)
            .first
        )

        self.perbarui_data_pelanggan_modal = page.locator(
            'section[role="dialog"]:has(.mantine-Text-root:has-text("Perbarui Data Pelanggan"))'
        )

        self.perbarui_data_pelanggan_tutup = (
            self.perbarui_data_pelanggan_modal.get_by_role("button").filter(
                has_text=re.compile(r"^\s*tutup\s*$", re.IGNORECASE)
            )
        )

        nib_reminder_title = (
            page.locator("div.mantine-Text-root")
            .filter(has_text=_NIB_REMINDER_TITLE)
            .filter(visible=True)
        )

        self.perbarui_data_nib_pelanggan_modal = (
            page.locator("section")
            .filter(has=nib_reminder_title)
            .filter(visible=True)
            .first
        )

        self.perbarui_data_nib_pelanggan_title = (
            self.perbarui_data_nib_pelanggan_modal.locator("div.mantine-Text-root")
            .filter(has_text=_NIB_REMINDER_TITLE)
            .filter(visible=True)
            .first
        )

        self.perbarui_data_nib_pelanggan_lanjut_nanti = (
            self.perbarui_data_nib_pelanggan_modal.locator("button")
            .filter(has_text=_NIB_CONTINUE_LATER_BUTTON)
            .filter(visible=True)
            .first
        )

        self.perbarui_data_nib_pelanggan_tutup = (
            self.perbarui_data_nib_pelanggan_modal.locator("button")
            .filter(has_text=_NIB_TUTUP_BUTTON)
            .filter(visible=True)
            .first
        )

        self.nik_under_17_validation = (
            page.locator("div.mantine-Text-root")
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_NIK_UNDER_17_VALIDATION_TEXT)}\s*$",
                    re.IGNORECASE,
                )
            )
            .first
        )

        self.invalid_registered_nik_modal = (
            page.get_by_role("dialog")
            .filter(
                has_text=re.compile(
                    re.escape(_INVALID_REGISTERED_NIK_MESSAGE), re.IGNORECASE
                )
            )
            .first
        )

        self.invalid_registered_nik_modal_title = (
            self.invalid_registered_nik_modal.locator(
                "h6.mantine-Text-root.mantine-Title-root"
            )
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_INVALID_REGISTERED_NIK_MODAL_TITLE)}\s*$",
                    re.IGNORECASE,
                )
            )
            .first
        )

        self.invalid_registered_nik_modal_message = (
            self.invalid_registered_nik_modal.locator("div.mantine-Text-root")
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_INVALID_REGISTERED_NIK_MESSAGE)}\s*$",
                    re.IGNORECASE,
                )
            )
            .first
        )

        self.invalid_registered_nik_modal_tutup = (
            self.invalid_registered_nik_modal.get_by_role(
                "button",
                name=re.compile(r"^\s*tutup\s*$", re.IGNORECASE),
            ).first
        )

        self.cannot_transact_at_base_modal = (
            page.get_by_role("dialog")
            .filter(
                has_text=re.compile(
                    re.escape(_CANNOT_TRANSACT_AT_BASE_TITLE), re.IGNORECASE
                )
            )
            .first
        )

        self.cannot_transact_at_base_modal_title = (
            self.cannot_transact_at_base_modal.locator(
                "h6.mantine-Text-root.mantine-Title-root"
            )
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_CANNOT_TRANSACT_AT_BASE_TITLE)}\s*$",
                    re.IGNORECASE,
                )
            )
            .first
        )

        self.cannot_transact_at_base_modal_tutup = (
            self.cannot_transact_at_base_modal.get_by_role(
                "button",
                name=re.compile(r"^\s*tutup\s*$", re.IGNORECASE),
            ).first
        )

        self.unusual_transaction_modal = (
            page.get_by_role("dialog")
            .filter(
                has_text=re.compile(
                    re.escape(_UNUSUAL_TRANSACTION_MESSAGE), re.IGNORECASE
                )
            )
            .first
        )
        self.unusual_transaction_modal_title = (
            self.unusual_transaction_modal.locator(
                "h6.mantine-Text-root.mantine-Title-root"
            )
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_UNUSUAL_TRANSACTION_MODAL_TITLE)}\s*$",
                    re.IGNORECASE,
                )
            )
            .first
        )

        self.unusual_transaction_modal_message = (
            self.unusual_transaction_modal.locator("div.mantine-Text-root")
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_UNUSUAL_TRANSACTION_MESSAGE)}\s*$", re.IGNORECASE
                )
            )
            .first
        )

        self.unusual_transaction_modal_tutup = (
            self.unusual_transaction_modal.get_by_role(
                "button",
                name=re.compile(r"^\s*tutup\s*$", re.IGNORECASE),
            ).first
        )

        self.failed_puzzle_modal = (
            page.get_by_role("dialog")
            .filter(
                has_text=re.compile(
                    re.escape(_FAILED_PUZZLE_MODAL_TITLE), re.IGNORECASE
                )
            )
            .first
        )

        self.failed_puzzle_modal_title = (
            self.failed_puzzle_modal.get_by_role("heading")
            .filter(
                has_text=re.compile(
                    rf"^\s*{re.escape(_FAILED_PUZZLE_MODAL_TITLE)}\s*$", re.IGNORECASE
                )
            )
            .first
        )

    def debug_interaction_state(self, label: str) -> None:
        """Capture a best-effort DOM snapshot when interaction debugging is enabled."""
        diagnostics = get_page_diagnostics(getattr(self, "page", object()))
        if diagnostics is not None:
            diagnostics.debug_interaction_state(label)

    def _debug_interaction_checkpoint(
        self,
        label: str,
        *,
        target_name: str | None = None,
        target_locator: Locator | None = None,
        target_locator_factory: Callable[[], Locator] | None = None,
    ) -> None:
        diagnostics = get_page_diagnostics(getattr(self, "page", object()))
        if diagnostics is None:
            return
        self.debug_interaction_state(label)
        if target_locator is None and target_locator_factory is not None:
            try:
                target_locator = target_locator_factory()
            except Exception:  # noqa: BLE001 - diagnostic lookup must not alter workflow.
                target_locator = None
        if target_name is not None and target_locator is not None:
            diagnostics.debug_target_locator(label, target_name, target_locator)
        diagnostics.screenshot(label)

    def _debug_pause(self, label: str) -> None:
        diagnostics = get_page_diagnostics(getattr(self, "page", object()))
        if diagnostics is not None:
            diagnostics.pause(label)

    def _debug_poll_interaction_states(self, label: str) -> None:
        diagnostics = get_page_diagnostics(getattr(self, "page", object()))
        if diagnostics is None:
            return
        diagnostics.poll_state_changes(
            label,
            self._debug_interaction_state_probes(),
            duration_ms=20_000,
            interval_ms=250,
            on_change=self._debug_state_changed,
        )

    def _debug_state_changed(
        self,
        state_name: str,
        previous: bool | None,
        current: bool,
        elapsed_ms: int,
    ) -> None:
        del elapsed_ms
        if state_name != "nib_tutup_visible" or not current or previous is True:
            return
        self._debug_interaction_checkpoint(
            "nib_tutup_detected",
            target_name="NIB Tutup",
            target_locator_factory=lambda: self._debug_nib_button_collection(
                _NIB_TUTUP_BUTTON
            ),
        )
        self._debug_pause("nib_tutup_detected")

    def _debug_interaction_state_probes(self):
        return {
            "customer_type_modal_visible": lambda: self._debug_any_visible(
                self._debug_customer_type_modal_collection()
            ),
            "continue_button_visible": lambda: self._debug_any_visible(
                self._debug_customer_type_continue_collection()
            ),
            "nib_modal_visible": lambda: self._debug_any_visible(
                self._debug_nib_modal_collection()
            ),
            "nib_continue_visible": lambda: self._debug_any_visible(
                self._debug_nib_button_collection(_NIB_CONTINUE_LATER_BUTTON)
            ),
            "nib_tutup_visible": lambda: self._debug_any_visible(
                self._debug_nib_button_collection(_NIB_TUTUP_BUTTON)
            ),
            "transaction_form_visible": lambda: self._is_visible(
                self.cek_pesanan_button
            ),
            "other_precheck_modal_visible": self._debug_other_precheck_visible,
        }

    def _debug_customer_type_modal_collection(self) -> Locator:
        marker = re.compile(
            r"Jenis\s+Pelanggan|"
            r"Pelanggan\s+Terdaftar|"
            r"pilihan\s+jenis\s+pelanggan",
            re.IGNORECASE,
        )
        return self.page.locator("section").filter(has_text=marker)

    def _debug_customer_type_continue_collection(self) -> Locator:
        button_pattern = re.compile(
            r"^\s*LANJUTKAN\s+PENJUALAN\s*$",
            re.IGNORECASE,
        )
        return (
            self._debug_customer_type_modal_collection()
            .locator("button")
            .filter(has_text=button_pattern)
        )

    def _debug_nib_modal_collection(self) -> Locator:
        titles = self.page.locator("div.mantine-Text-root").filter(
            has_text=_NIB_REMINDER_TITLE
        )
        return self.page.locator("section").filter(has=titles)

    def _debug_nib_button_collection(self, pattern: re.Pattern[str]) -> Locator:
        return (
            self._debug_nib_modal_collection()
            .locator("button")
            .filter(has_text=pattern)
        )

    @staticmethod
    def _debug_any_visible(collection: Locator) -> bool:
        try:
            count = collection.count()
        except PlaywrightError:
            return False
        for index in range(count):
            try:
                if collection.nth(index).is_visible():
                    return True
            except PlaywrightError:
                continue
        return False

    def _debug_other_precheck_visible(self) -> bool:
        return any(
            self._is_visible(locator)
            for locator in (
                self.pelanggan_tidak_terdaftar_modal,
                self.registration_request_limited_modal,
                self.perbarui_data_pelanggan_modal,
                self.invalid_registered_nik_modal,
                self.cannot_transact_at_base_modal,
                self.unusual_transaction_modal,
            )
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

    def detect_zero_stock_modal(
        self,
        detect_timeout: int = 5000,
    ) -> bool:
        try:
            self.zero_stock_modal.wait_for(
                state="visible",
                timeout=detect_timeout,
            )
        except TimeoutError:
            return False

        log_print("Zero-stock modal detected: Stok Tabung Kosong")
        return True

    def dismiss_zero_stock_modal(self) -> None:
        self.click_locator(
            self.zero_stock_modal_tutup,
            action_name="closing Stok Tabung Kosong modal",
            expected_text="TUTUP",
            timeout_ms=5000,
            load_state=None,
        )

        try:
            self.zero_stock_modal.wait_for(
                state="hidden",
                timeout=5000,
            )
        except TimeoutError:
            log_print(
                "Stok Tabung Kosong modal remained visible after TUTUP was clicked."
            )

        log_print("Stok Tabung Kosong modal closed")

    def catat_penjualan(self, nik: str) -> CatatPenjualanOutcome:
        if self._is_visible(self.registration_request_limited_modal):
            log_print(
                "Customer registration request-limit modal is already visible; "
                "deferring to customer prechecks."
            )
            return "registration_request_limited"

        already_on_form = False

        try:
            self.nik_input.wait_for(
                state="visible",
                timeout=800,
            )
            already_on_form = True
            log_print("NIK input already visible; skipping tile click")
        except TimeoutError:
            pass

        if not already_on_form:
            for attempt in range(1, _ZERO_STOCK_CONFIRM_ATTEMPTS + 1):
                log_print(
                    f"Opening Catat Penjualan "
                    f"(attempt {attempt}/{_ZERO_STOCK_CONFIRM_ATTEMPTS})"
                )

                self.click_locator(
                    self.catat_penjualan_tile,
                    action_name="opening Catat Penjualan",
                    expected_text="Catat Penjualan",
                    timeout_ms=5000,
                    load_state=None,
                )

                try:
                    self.nik_input.or_(self.zero_stock_modal).first.wait_for(
                        state="visible",
                        timeout=5000,
                    )
                except TimeoutError as exc:
                    raise RuntimeError(
                        "Neither NIK input nor 'Stok Tabung Kosong' modal "
                        "appeared after clicking Catat Penjualan."
                    ) from exc

                # Normal transaction form appeared.
                if self._is_visible(self.nik_input):
                    log_print("NIK input appeared; Catat Penjualan is ready.")
                    break

                # Zero-stock modal appeared.
                if self._is_visible(self.zero_stock_modal):
                    log_print(
                        f"Stok Tabung Kosong detected "
                        f"(confirmation {attempt}/"
                        f"{_ZERO_STOCK_CONFIRM_ATTEMPTS})"
                    )

                    self.dismiss_zero_stock_modal()

                    # Do NOT immediately treat the first modal as real zero stock.
                    if attempt < _ZERO_STOCK_CONFIRM_ATTEMPTS:
                        # Before the final attempt, reload the dashboard once
                        # to avoid relying on stale frontend stock state.
                        if attempt == _ZERO_STOCK_CONFIRM_ATTEMPTS - 1:
                            log_print(
                                "Zero stock detected repeatedly; "
                                "refreshing dashboard before final confirmation."
                            )

                            self.page.reload(
                                wait_until="load",
                                timeout=10000,
                            )

                            expect(self.catat_penjualan_tile).to_be_visible(
                                timeout=8000
                            )

                        log_print(
                            f"Waiting {_ZERO_STOCK_RETRY_DELAY_MS}ms "
                            "before checking stock again."
                        )

                        self.page.wait_for_timeout(_ZERO_STOCK_RETRY_DELAY_MS)

                        continue

                    # Zero-stock was confirmed multiple times.
                    log_print(
                        "Stok Tabung Kosong confirmed after "
                        f"{_ZERO_STOCK_CONFIRM_ATTEMPTS} attempts."
                    )

                    return "zero_stock"

            else:
                # Defensive fallback. Normally the loop either breaks
                # because the NIK form appears or returns zero_stock.
                raise RuntimeError("Unable to determine Catat Penjualan state.")

            expect(self.nik_input).to_be_visible(timeout=3000)

        try:
            self.fill_input(
                self.nik_input,
                str(nik),
                action_name=f"filling NIK {nik}",
            )
        except PlaywrightError, AssertionError:
            if self._is_visible(self.registration_request_limited_modal):
                log_print(
                    "Customer registration request-limit modal interrupted NIK fill; "
                    "deferring to customer prechecks."
                )
                return "registration_request_limited"
            raise
        log_print("NIK input filled with:", nik)

        if self._is_visible(self.registration_request_limited_modal):
            log_print(
                "Customer registration request-limit modal appeared during NIK "
                "fill; deferring to customer prechecks."
            )
            return "registration_request_limited"

        # Mantine renders matching NIKs in a portal below this combobox. On a
        # same-NIK restart that suggestion can cover LANJUTKAN PENJUALAN even
        # though Playwright correctly reports the button as visible/enabled.
        # Dismiss the popup instead of force-clicking through a real overlay.
        try:
            self.nik_input.press("Escape")
        except PlaywrightError:
            if self._is_visible(self.registration_request_limited_modal):
                return "registration_request_limited"
            raise
        log_print("NIK autocomplete dismissed before continuing sale")

        if self._is_visible(self.registration_request_limited_modal):
            log_print(
                "Customer registration request-limit modal appeared before sale "
                "continuation; deferring to customer prechecks."
            )
            return "registration_request_limited"

        try:
            self.click_locator(
                self.lanjutkan_penjualan_button,
                action_name=f"continuing sale for NIK {nik}",
                expected_text="LANJUTKAN PENJUALAN",
                timeout_ms=5000,
                load_state=None,
            )
        except PlaywrightError, AssertionError:
            if self._is_visible(self.registration_request_limited_modal):
                log_print(
                    "Customer registration request-limit modal interrupted sale "
                    "continuation; deferring to customer prechecks."
                )
                return "registration_request_limited"
            raise

        log_print("Lanjutkan Penjualan button clicked")

        return "ready"

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

        return self.get_visible_customer_entry()

    def get_visible_customer_entry(self) -> CustomerEntryOutcome:
        """Return a non-waiting snapshot of the current customer-entry UI."""
        if self._is_visible(self.nik_under_17_validation):
            return "under_17"

        if self.get_visible_precheck_modal() is not None:
            return "precheck_modal"

        if self._is_visible(self.jenis_pelanggan_modal):
            return "customer_type"

        if self._is_visible(self.transaction_blocker_alert):
            return "transaction_blocked"

        if self._is_visible(self.cek_pesanan_button) and not self._has_visible_dialog():
            return "transaction_ready"

        return "unknown"

    def is_transaction_form_ready(self, detect_timeout: int = 700) -> bool:
        try:
            self.cek_pesanan_button.wait_for(state="visible", timeout=detect_timeout)
        except TimeoutError:
            log_print("Transaction form not ready yet; checking blocking modals.")
            return False

        if self._has_visible_blocking_transaction_dialog():
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

    def wait_for_transaction_form_or_precheck_modal(
        self, detect_timeout: int = 6000
    ) -> PostCustomerEntryOutcome:
        try:
            self.cek_pesanan_button.or_(self._precheck_modal_locator()).first.wait_for(
                state="visible", timeout=detect_timeout
            )
        except TimeoutError:
            log_print("No transaction form or known pre-check modal became visible.")
            return "unknown"

        if self.is_transaction_form_ready(detect_timeout=100):
            return "transaction_ready"
        if self.get_visible_precheck_modal() is not None:
            return "precheck_modal"
        return "unknown"

    def get_visible_precheck_modal(self) -> PrecheckModalName | None:
        for modal_name, modal in [
            ("not_registered", self.pelanggan_tidak_terdaftar_modal),
            (
                "registration_request_limited",
                self.registration_request_limited_modal,
            ),
            ("invalid_registered_nik", self.invalid_registered_nik_modal),
            ("cannot_transact_at_base", self.cannot_transact_at_base_modal),
            ("unusual_transaction", self.unusual_transaction_modal),
            ("nib_reminder", self.perbarui_data_nib_pelanggan_modal),
            ("perbarui", self.perbarui_data_pelanggan_modal),
        ]:
            if self._is_visible(modal):
                return modal_name
        return None

    def select_jenis_pelanggan_if_needed(
        self,
        detect_timeout: int = 5000,
    ) -> bool:
        try:
            self.jenis_pelanggan_modal.wait_for(
                state="visible",
                timeout=detect_timeout,
            )
        except TimeoutError:
            log_print("Jenis Pelanggan modal not present; skipping.")
            return False

        self.select_jenis_pelanggan()
        return True

    def select_jenis_pelanggan(self) -> None:
        """
        Select a usable customer type and continue.

        The target application is asynchronous. A successful Playwright click
        is therefore not treated as proof that the application accepted the
        action. Both the radio selection and the continue action are verified
        from the resulting UI state.
        """

        expect(self.jenis_pelanggan_modal).to_be_visible(timeout=15000)

        selection = self._find_customer_type_choice()
        if selection is None:
            raise RuntimeError(
                "Jenis Pelanggan modal is visible, but no usable "
                "customer-type option could be found."
            )

        option_name, choice = selection
        log_print(f"Jenis Pelanggan option selected for interaction: {option_name}")

        self._select_customer_type_with_confirmation(option_name, choice)
        self._debug_interaction_checkpoint("customer_type_radio_confirmed")
        self._debug_pause("customer_type_radio_confirmed_before_continue")

        # The button can be rendered before the backend/UI state is fully ready.
        # Wait and retry only when the SAME customer-type modal remains visible.
        self._continue_jenis_pelanggan_with_confirmation(option_name)

    def _find_customer_type_choice(
        self,
    ) -> tuple[str, Locator] | None:
        """
        Find a customer-type option without relying on generated CSS classes.

        Prefer the known business order:
        Rumah Tangga -> Usaha Mikro.

        If neither known label can be resolved, fall back to the first
        visible/enabled semantic radio control.
        """

        for option_name in (
            "Rumah Tangga",
            "Usaha Mikro",
        ):
            log_print(f"Inspecting Jenis Pelanggan option: {option_name}")

            choice = self._find_named_customer_type_choice(option_name)

            if choice is not None:
                return option_name, choice

            log_print(
                f"Jenis Pelanggan option '{option_name}' "
                "not usable; trying next option."
            )

        log_print(
            "Known Jenis Pelanggan options were not usable; "
            "trying generic radio fallback."
        )

        generic_choice = self._find_first_available_customer_type_choice()

        if generic_choice is not None:
            return "first visible/enabled customer type", generic_choice

        return None

    def _customer_type_is_selected(
        self,
        option_name: str,
    ) -> bool:
        if option_name in {"Rumah Tangga", "Usaha Mikro"}:
            return self._is_named_customer_type_selected(option_name)

        return self._is_any_customer_type_selected()

    def _is_named_customer_type_selected(
        self,
        option_name: str,
    ) -> bool:
        """
        Verify a known customer type using both:

        1. native radio checked state
        2. application's visible "Terpilih" state

        The second check is important because this site uses a custom styled
        radio component and its rendered selected state is authoritative UI
        evidence that the application accepted the selection.
        """

        radio = self.jenis_pelanggan_modal.locator(
            f'input[type="radio"][value="{option_name}"]'
        ).first

        # First preference: actual native checked property.
        try:
            if radio.count() > 0 and radio.is_checked():
                log_print(f"Customer type native radio is checked: {option_name}")
                return True
        except PlaywrightError:
            pass

        # Second signal: the website itself visually reports "Terpilih"
        # inside the label belonging to this exact radio.
        label = self.jenis_pelanggan_modal.locator(
            f'label:has(input[type="radio"][value="{option_name}"])'
        ).first

        try:
            if label.count() == 0 or not label.is_visible():
                return False

            selected_status = label.get_by_text(
                "Terpilih",
                exact=True,
            )

            if selected_status.count() > 0 and selected_status.is_visible():
                log_print(f"Customer type visual selection confirmed: {option_name}")
                return True

        except PlaywrightError:
            pass

        return False

    def _is_any_customer_type_selected(self) -> bool:
        """Check whether any customer-type radio is actually selected."""

        scope = self.jenis_pelanggan_modal

        native_radios = scope.locator("input[type='radio']")

        try:
            count = native_radios.count()
        except PlaywrightError:
            count = 0

        for index in range(count):
            radio = native_radios.nth(index)

            try:
                if radio.is_checked():
                    return True
            except PlaywrightError:
                continue

        aria_radios = scope.locator('[role="radio"]')

        try:
            count = aria_radios.count()
        except PlaywrightError:
            count = 0

        for index in range(count):
            radio = aria_radios.nth(index)

            try:
                if radio.get_attribute("aria-checked") == "true":
                    return True
            except PlaywrightError:
                continue

        return False

    def _wait_for_customer_type_selection(
        self,
        option_name: str,
        timeout_ms: int = _CUSTOMER_TYPE_SELECTION_VERIFY_MS,
    ) -> bool:
        """Wait for the selected radio state to propagate through the UI."""

        interval_ms = 100
        attempts = max(1, timeout_ms // interval_ms)

        for _ in range(attempts):
            if self._customer_type_is_selected(option_name):
                return True

            self.page.wait_for_timeout(interval_ms)

        return self._customer_type_is_selected(option_name)

    def _select_customer_type_with_confirmation(
        self,
        option_name: str,
        initial_choice: Locator,
    ) -> None:
        """
        Select the requested customer type and verify that the UI actually
        entered the checked state.

        Retrying selection is safe because the same radio option is used
        every time. We do not switch customer types merely because the
        frontend was slow to acknowledge the first click.
        """

        choice = initial_choice

        for attempt in range(
            1,
            _CUSTOMER_TYPE_SELECTION_ATTEMPTS + 1,
        ):
            # It may already have become selected while React was rerendering.
            if self._customer_type_is_selected(option_name):
                log_print(f"Jenis Pelanggan '{option_name}' is already selected.")
                return

            log_print(
                f"Selecting Jenis Pelanggan '{option_name}' "
                f"(attempt {attempt}/"
                f"{_CUSTOMER_TYPE_SELECTION_ATTEMPTS})"
            )

            self._debug_interaction_checkpoint("customer_type_radio_before_click")
            try:
                choice.scroll_into_view_if_needed(timeout=3000)

                choice.click(timeout=5000)

            except PlaywrightError as exc:
                log_print(
                    f"Click on Jenis Pelanggan '{option_name}' "
                    "did not complete cleanly.",
                    exc,
                )
            finally:
                self._debug_interaction_checkpoint("customer_type_radio_after_click")

            if self._wait_for_customer_type_selection(option_name):
                log_print(f"Jenis Pelanggan selection confirmed: {option_name}")
                return

            log_print(
                f"Jenis Pelanggan '{option_name}' was clicked but "
                "the radio is still not selected."
            )

            if attempt >= _CUSTOMER_TYPE_SELECTION_ATTEMPTS:
                break

            # React may have replaced the original node. Re-resolve the
            # locator instead of relying on the previous DOM element.
            if option_name in {"Rumah Tangga", "Usaha Mikro"}:
                refreshed_choice = self._find_named_customer_type_choice(option_name)
            else:
                refreshed_choice = self._find_first_available_customer_type_choice()

            if refreshed_choice is not None:
                choice = refreshed_choice

            self.page.wait_for_timeout(300)

        raise RuntimeError(
            f"Jenis Pelanggan '{option_name}' could not be confirmed "
            f"as selected after "
            f"{_CUSTOMER_TYPE_SELECTION_ATTEMPTS} attempts."
        )

    def _find_named_customer_type_choice(
        self,
        option_name: str,
    ) -> Locator | None:
        """
        Locate a customer-type option using the radio's stable value attribute.

        The wrapping label is the preferred click target because this application
        implements a custom styled radio component.
        """

        radio = self.jenis_pelanggan_modal.locator(
            f'input[type="radio"][value="{option_name}"]'
        ).first

        try:
            if radio.count() == 0:
                log_print(f"Customer type radio not found by value: {option_name}")
                return None
        except PlaywrightError:
            return None

        # Prefer clicking the visible wrapping label rather than the possibly
        # visually-hidden/custom-styled native radio input.
        label = self.jenis_pelanggan_modal.locator(
            f'label:has(input[type="radio"][value="{option_name}"])'
        ).first

        try:
            if label.count() > 0 and label.is_visible():
                log_print(f"Customer type label found by radio value: {option_name}")
                return label
        except PlaywrightError:
            pass

        # Fallback to native radio if it is itself usable.
        try:
            if radio.is_visible() and radio.is_enabled():
                log_print(f"Using native customer type radio: {option_name}")
                return radio
        except PlaywrightError:
            pass

        return None

    def _find_first_available_customer_type_choice(
        self,
    ) -> Locator | None:
        """
        Generic fallback when the known customer labels cannot be resolved.

        This allows the automation to survive markup changes while still
        avoiding generated CSS classes.
        """

        scope = self.jenis_pelanggan_modal

        candidates = (
            # Best case: accessible semantic radios.
            scope.get_by_role("radio"),
            # Common custom-radio implementation:
            # visible label wrapping a hidden native radio.
            scope.locator("label:has(input[type='radio'])"),
            # Last semantic fallback.
            scope.locator("input[type='radio']"),
        )

        for collection in candidates:
            choice = self._first_usable_locator(collection)

            if choice is not None:
                return choice

        return None

    def _find_jenis_pelanggan_continue_button(
        self,
    ) -> Locator | None:
        """
        Locate the visible LANJUTKAN PENJUALAN button.

        Plain DOM button lookup is preferred here because Mantine portals can be
        visually active while an ancestor is aria-hidden, which can make role
        selectors ignore the live button.
        """

        button_pattern = re.compile(
            r"^\s*LANJUTKAN\s+PENJUALAN\s*$",
            re.IGNORECASE,
        )

        candidates = (
            self.jenis_pelanggan_modal.locator("button")
            .filter(has_text=button_pattern)
            .filter(visible=True),
            self.jenis_pelanggan_modal.get_by_role(
                "button",
                name=button_pattern,
            ),
            # Last fallback: visible exact-text button anywhere in the current
            # portal. The modal visibility checks around the click prevent this
            # fallback from being used after the flow has already transitioned.
            self.page.locator("button")
            .filter(has_text=button_pattern)
            .filter(visible=True),
        )

        for collection in candidates:
            button = self._first_usable_locator(
                collection,
                require_enabled=False,
            )
            if button is not None:
                return button

        return None

    def _continue_jenis_pelanggan_with_confirmation(
        self,
        option_name: str,
    ) -> None:
        """
        Click LANJUTKAN PENJUALAN and confirm an actual state transition.

        A retry happens only when:
        - the same Jenis Pelanggan modal is still visible,
        - no known next modal/state has appeared, and
        - the previous click had a full post-click observation window.

        This avoids racing a slow target application while still recovering
        when a click was visually performed but not accepted by the app.
        """

        for attempt in range(1, _CUSTOMER_TYPE_CONTINUE_ATTEMPTS + 1):
            if not self._is_visible(self.jenis_pelanggan_modal):
                log_print(
                    "Jenis Pelanggan modal already disappeared; "
                    "continue action was accepted."
                )
                return

            # React may re-render and lose the selected state before the action.
            if not self._customer_type_is_selected(option_name):
                log_print(
                    "Jenis Pelanggan selection is no longer active; "
                    "re-selecting before continuing."
                )

                refreshed_choice = (
                    self._find_named_customer_type_choice(option_name)
                    if option_name in {"Rumah Tangga", "Usaha Mikro"}
                    else self._find_first_available_customer_type_choice()
                )
                if refreshed_choice is None:
                    raise RuntimeError(
                        "Customer-type selection disappeared and could not "
                        "be located again."
                    )

                self._select_customer_type_with_confirmation(
                    option_name,
                    refreshed_choice,
                )

            continue_button = self._wait_for_jenis_pelanggan_continue_button()
            if continue_button is None:
                raise RuntimeError(
                    "Jenis Pelanggan is selected, but LANJUTKAN PENJUALAN "
                    "did not become visible."
                )

            try:
                expect(continue_button).to_be_enabled(timeout=15000)
            except AssertionError as exc:
                # If the modal vanished while waiting, the previous action won.
                if not self._is_visible(self.jenis_pelanggan_modal):
                    return
                raise RuntimeError(
                    "LANJUTKAN PENJUALAN remained disabled after selecting "
                    "Jenis Pelanggan."
                ) from exc

            # Small stabilization check: ensure the selected state still exists
            # after the button becomes enabled.
            if not self._customer_type_is_selected(option_name):
                log_print(
                    "Customer type changed while waiting for the continue "
                    "button; retrying selection."
                )
                continue

            log_print(
                "Clicking LANJUTKAN PENJUALAN from Jenis Pelanggan "
                f"(attempt {attempt}/{_CUSTOMER_TYPE_CONTINUE_ATTEMPTS})."
            )

            self._debug_interaction_checkpoint(
                "customer_type_continue_before_click",
                target_name="Jenis Pelanggan LANJUTKAN PENJUALAN",
                target_locator_factory=self._debug_customer_type_continue_collection,
            )
            try:
                continue_button.scroll_into_view_if_needed(timeout=5000)

                expect(continue_button).to_be_visible(timeout=5000)

                expect(continue_button).to_be_enabled(timeout=5000)

                log_print(
                    "Clicking LANJUTKAN PENJUALAN using direct "
                    "Playwright locator.click()"
                )

                continue_button.click(timeout=15000)
            except (PlaywrightError, AssertionError, TimeoutError) as exc:
                # A Playwright-side click error does not necessarily mean the
                # target ignored the action. Check post-state before failing.
                if self._wait_for_jenis_pelanggan_transition(timeout_ms=3000):
                    log_print(
                        "Jenis Pelanggan transitioned despite a click-side "
                        "exception; treating the action as successful."
                    )
                    return

                log_print(
                    "LANJUTKAN PENJUALAN click did not produce an immediate "
                    "transition.",
                    exc,
                )
            finally:
                self._debug_interaction_checkpoint(
                    "customer_type_continue_after_click",
                    target_name="Jenis Pelanggan LANJUTKAN PENJUALAN",
                    target_locator_factory=self._debug_customer_type_continue_collection,
                )
                self._debug_poll_interaction_states(
                    "customer_type_continue_post_click_20s"
                )

            if self._wait_for_jenis_pelanggan_transition(
                timeout_ms=_CUSTOMER_TYPE_CONTINUE_RESULT_TIMEOUT_MS
            ):
                log_print("Jenis Pelanggan continue action confirmed by UI transition.")
                return

            followup_state = self._get_customer_type_followup_state()

            if followup_state is not None:
                log_print(
                    "Next workflow state detected after Jenis Pelanggan: "
                    f"{followup_state}"
                )
                return

            if not self._is_visible(self.jenis_pelanggan_modal):
                return

            if attempt < _CUSTOMER_TYPE_CONTINUE_ATTEMPTS:
                log_print(
                    "Jenis Pelanggan modal remains the active workflow state "
                    "after the full post-click wait; reacquiring the button "
                    "and retrying."
                )

                self.page.wait_for_timeout(500)

        raise RuntimeError(
            "LANJUTKAN PENJUALAN from Jenis Pelanggan did not produce "
            "a state transition after "
            f"{_CUSTOMER_TYPE_CONTINUE_ATTEMPTS} verified attempts."
        )

    def _wait_for_jenis_pelanggan_continue_button(
        self,
        timeout_ms: int = 15000,
    ) -> Locator | None:
        """Wait for the live continue button to be rendered in the active modal."""

        elapsed = 0
        poll_ms = 200

        while elapsed < timeout_ms:
            if not self._is_visible(self.jenis_pelanggan_modal):
                return None

            button = self._find_jenis_pelanggan_continue_button()
            if button is not None and self._is_visible(button):
                return button

            self.page.wait_for_timeout(poll_ms)
            elapsed += poll_ms

        return self._find_jenis_pelanggan_continue_button()

    def _get_customer_type_followup_state(self) -> str | None:
        """
        Detect a valid state that may appear after Jenis Pelanggan.

        Important:
        Mantine may keep the previous customer-type dialog visible briefly
        while the next modal/page is already active on top of it.
        """

        # Transaction form became available directly.
        if self.is_transaction_form_ready(detect_timeout=100):
            return "transaction_ready"

        # Optional consent page.
        consent_marker = self.page.get_by_text(
            _CUSTOMER_TYPE_CONSENT_MARKER,
        ).first

        if self._is_visible(consent_marker):
            return "consent"

        # Customer data update-required modal.
        update_required_marker = self.page.get_by_text(
            _CUSTOMER_TYPE_UPDATE_REQUIRED_MARKER,
        ).first

        if self._is_visible(update_required_marker):
            return "update_required"

        # Existing Dashboard-managed precheck modals:
        # NIB, not registered, unusual transaction, etc.
        next_modal = self.get_visible_precheck_modal()

        if next_modal is not None:
            return next_modal

        return None

    def _wait_for_jenis_pelanggan_transition(
        self,
        *,
        timeout_ms: int,
    ) -> bool:
        """
        Observe whether the customer-type action moved to another workflow state.

        Do not require the old Mantine modal to disappear first. The application
        can render the next modal while the previous one is still present during
        its closing transition.
        """

        elapsed = 0

        while elapsed < timeout_ms:
            followup_state = self._get_customer_type_followup_state()

            if followup_state is not None:
                log_print(
                    "Jenis Pelanggan transitioned to next workflow state: "
                    f"{followup_state}"
                )
                return True

            # Normal case: old modal simply disappeared.
            if not self._is_visible(self.jenis_pelanggan_modal):
                log_print(
                    "Jenis Pelanggan modal disappeared; continue action accepted."
                )
                return True

            self.page.wait_for_timeout(_CUSTOMER_TYPE_CONTINUE_POLL_MS)
            elapsed += _CUSTOMER_TYPE_CONTINUE_POLL_MS

        # One final observation at timeout boundary.
        followup_state = self._get_customer_type_followup_state()

        if followup_state is not None:
            log_print(
                f"Jenis Pelanggan transitioned to next workflow state: {followup_state}"
            )
            return True

        return not self._is_visible(self.jenis_pelanggan_modal)

    def _first_usable_locator(
        self,
        collection: Locator,
        *,
        require_enabled: bool = True,
    ) -> Locator | None:
        """
        Return the first visible/actionable locator from a collection.
        """

        try:
            count = collection.count()
        except PlaywrightError as exc:
            raise RuntimeError("Unable to inspect Jenis Pelanggan controls.") from exc

        for index in range(count):
            candidate = collection.nth(index)

            try:
                if not candidate.is_visible():
                    continue

                if require_enabled and not candidate.is_enabled():
                    continue

                return candidate

            except PlaywrightError:
                # DOM may have rerendered while inspecting.
                # Try the next current candidate.
                continue

        return None

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

    def read_registration_request_limited_reason_if_present(
        self, detect_timeout: int = 6000
    ) -> str | None:
        return self._read_simple_warning_modal_reason_if_present(
            modal=self.registration_request_limited_modal,
            detect_timeout=detect_timeout,
            missing_log=(
                "Customer registration request-limit modal not present; continuing."
            ),
            title_locator=self.registration_request_limited_title,
            title_fallback=_REGISTRATION_REQUEST_LIMITED_MODAL_TITLE_TEXT,
            title_detect_log="Detected customer registration request-limit title",
            message_locator=self.registration_request_limited_message,
            message_fallback=_REGISTRATION_REQUEST_LIMITED_MESSAGE_TEXT,
            message_detect_log="Detected customer registration request limit",
            missing_content_log=(
                "Customer registration request-limit modal became visible without "
                "the expected message."
            ),
        )

    def dismiss_registration_request_limited_modal(self) -> None:
        self.click_locator(
            self.registration_request_limited_tutup,
            action_name="closing customer registration request-limit modal",
            expected_text="Tutup",
            timeout_ms=5000,
            load_state=None,
        )
        try:
            self.registration_request_limited_modal.wait_for(
                state="hidden", timeout=7000
            )
        except TimeoutError:
            # The click is one-shot. A slow stale portal is resolved by the
            # central state machine; never click the server-limit action twice.
            log_print(
                "Customer registration request-limit modal remained visible "
                "after Tutup was clicked."
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

    def detect_perbarui_data_nib_pelanggan_if_needed(
        self, detect_timeout: int = 6000
    ) -> bool:
        try:
            self.perbarui_data_nib_pelanggan_modal.wait_for(
                state="visible", timeout=detect_timeout
            )
            return True
        except TimeoutError:
            log_print("Perbarui Data NIB Pelanggan modal not present; continuing.")
            return False

    def continue_perbarui_data_nib_pelanggan(self) -> None:
        """Continue past the distinct Usaha Mikro NIB reminder exactly once."""
        self.perbarui_data_nib_pelanggan_modal.wait_for(state="visible", timeout=5000)
        self._debug_interaction_checkpoint(
            "nib_modal_detected",
            target_name="NIB NANTI SAJA",
            target_locator_factory=lambda: self._debug_nib_button_collection(
                _NIB_CONTINUE_LATER_BUTTON
            ),
        )
        self._debug_pause("nib_modal_detected")
        self._debug_interaction_checkpoint(
            "nib_continue_later_before_click",
            target_name="NIB NANTI SAJA",
            target_locator_factory=lambda: self._debug_nib_button_collection(
                _NIB_CONTINUE_LATER_BUTTON
            ),
        )
        try:
            self.click_locator(
                self.perbarui_data_nib_pelanggan_lanjut_nanti,
                action_name="continuing past Perbarui Data NIB Pelanggan modal",
                timeout_ms=5000,
                load_state=None,
            )
        finally:
            self._debug_interaction_checkpoint(
                "nib_continue_later_after_click",
                target_name="NIB NANTI SAJA",
                target_locator_factory=lambda: self._debug_nib_button_collection(
                    _NIB_CONTINUE_LATER_BUTTON
                ),
            )
            self._debug_poll_interaction_states("nib_continue_later_post_click_20s")
        log_print(
            "Clicked 'NANTI SAJA, LANJUT PENJUALAN' on the NIB reminder; "
            "continuing state detection."
        )

    def attempt_continue_perbarui_data_nib_pelanggan(
        self,
    ) -> PerbaruiDataPelangganAction:
        """
        Resolve the visible 'Segera Lengkapi NIB' modal.

        The important server-side behavior is asynchronous:
        after NANTI SAJA is clicked, the modal may disappear (success) OR the
        action may later be replaced with Tutup (transaction cannot continue).

        Never return "continued" merely because click() returned successfully.
        """

        if not self.detect_perbarui_data_nib_pelanggan_if_needed():
            return "not_present"

        log_print("Detected 'Segera Lengkapi NIB' modal.")
        self._debug_interaction_checkpoint(
            "nib_modal_detected",
            target_name="NIB NANTI SAJA",
            target_locator_factory=lambda: self._debug_nib_button_collection(
                _NIB_CONTINUE_LATER_BUTTON
            ),
        )
        self._debug_pause("nib_modal_detected")

        for attempt in range(1, _NIB_CONTINUE_ATTEMPTS + 1):
            # If the server has already changed the modal to the blocker state,
            # close it immediately.
            if self._is_visible(self.perbarui_data_nib_pelanggan_tutup):
                if self._dismiss_nib_tutup_with_confirmation():
                    return "close"
                return "cannot_continue"

            # The modal may have disappeared while we were checking.
            if not self._is_visible(self.perbarui_data_nib_pelanggan_modal):
                return "continued"

            if not self._is_visible(self.perbarui_data_nib_pelanggan_lanjut_nanti):
                log_print(
                    "NIB modal is visible but its action is still rendering; "
                    "waiting for NANTI SAJA or Tutup."
                )

                result = self._wait_for_nib_post_click_result(
                    timeout_ms=5000,
                    allow_modal_close=True,
                )
                if result == "close":
                    return "close"
                if result == "continued":
                    return "continued"

                if attempt < _NIB_CONTINUE_ATTEMPTS:
                    continue
                return "cannot_continue"

            log_print(
                "Clicking NIB continue-later action "
                f"(attempt {attempt}/{_NIB_CONTINUE_ATTEMPTS})."
            )

            self._debug_interaction_checkpoint(
                "nib_continue_later_before_click",
                target_name="NIB NANTI SAJA",
                target_locator_factory=lambda: self._debug_nib_button_collection(
                    _NIB_CONTINUE_LATER_BUTTON
                ),
            )
            try:
                self.click_locator(
                    self.perbarui_data_nib_pelanggan_lanjut_nanti,
                    action_name=(
                        "continuing transaction past 'Segera Lengkapi NIB' modal"
                    ),
                    timeout_ms=10000,
                    load_state=None,
                )
            except (PlaywrightError, AssertionError, TimeoutError) as exc:
                log_print(
                    "NIB continue-later click raised; observing the server "
                    "result before deciding whether to retry.",
                    exc,
                )
            finally:
                self._debug_interaction_checkpoint(
                    "nib_continue_later_after_click",
                    target_name="NIB NANTI SAJA",
                    target_locator_factory=lambda: self._debug_nib_button_collection(
                        _NIB_CONTINUE_LATER_BUTTON
                    ),
                )
                self._debug_poll_interaction_states("nib_continue_later_post_click_20s")

            # CRITICAL: do not return here. The target can respond slowly and
            # replace NANTI SAJA with Tutup several seconds after the click.
            result = self._wait_for_nib_post_click_result(
                timeout_ms=_NIB_POST_CLICK_TIMEOUT_MS,
                allow_modal_close=True,
            )

            if result == "continued":
                log_print("NIB continue-later action confirmed: modal disappeared.")
                return "continued"

            if result == "close":
                log_print(
                    "NIB continue-later was rejected by the target application; "
                    "Tutup was detected and closed."
                )
                return "close"

            # No transition after a full observation window. Re-clicking is
            # allowed only because the same modal and same continue action are
            # still visibly active.
            if attempt < _NIB_CONTINUE_ATTEMPTS:
                log_print(
                    "NIB modal remained unchanged after the full post-click "
                    "wait; retrying the continue-later action once."
                )
                self.page.wait_for_timeout(500)

        # Final defensive check before giving up.
        if (
            self._is_visible(self.perbarui_data_nib_pelanggan_tutup)
            and self._dismiss_nib_tutup_with_confirmation()
        ):
            return "close"

        if not self._is_visible(self.perbarui_data_nib_pelanggan_modal):
            return "continued"

        log_print("'Segera Lengkapi NIB' remained unresolved after verified attempts.")
        return "cannot_continue"

    def _wait_for_nib_post_click_result(
        self,
        *,
        timeout_ms: int,
        allow_modal_close: bool,
    ) -> Literal["continued", "close", "pending"]:
        """
        Poll the live NIB modal until the server exposes its real result.
        """

        elapsed = 0

        while elapsed < timeout_ms:
            if not self._is_visible(self.perbarui_data_nib_pelanggan_modal):
                return "continued"

            if self._is_visible(self.perbarui_data_nib_pelanggan_tutup):
                self._debug_interaction_checkpoint(
                    "nib_tutup_detected",
                    target_name="NIB Tutup",
                    target_locator_factory=lambda: self._debug_nib_button_collection(
                        _NIB_TUTUP_BUTTON
                    ),
                )
                self._debug_pause("nib_tutup_detected")
                if allow_modal_close and self._dismiss_nib_tutup_with_confirmation():
                    return "close"
                return "pending"

            self.page.wait_for_timeout(_NIB_POST_CLICK_POLL_MS)
            elapsed += _NIB_POST_CLICK_POLL_MS

        return "pending"

    def _dismiss_nib_tutup_with_confirmation(self) -> bool:
        """
        Click the NIB-specific Tutup button and verify that this exact modal
        actually disappears. Closing is safe to retry because it is not a
        transaction mutation.
        """

        for attempt in range(1, _NIB_TUTUP_CLICK_ATTEMPTS + 1):
            if not self._is_visible(self.perbarui_data_nib_pelanggan_modal):
                return True

            if not self._is_visible(self.perbarui_data_nib_pelanggan_tutup):
                return False

            log_print(
                "Clicking Tutup on 'Segera Lengkapi NIB' "
                f"(attempt {attempt}/{_NIB_TUTUP_CLICK_ATTEMPTS})."
            )

            self._debug_interaction_checkpoint(
                "nib_tutup_before_click",
                target_name="NIB Tutup",
                target_locator_factory=lambda: self._debug_nib_button_collection(
                    _NIB_TUTUP_BUTTON
                ),
            )
            try:
                # Re-resolve from the live visible modal each attempt.
                close_button = (
                    self.perbarui_data_nib_pelanggan_modal.locator("button")
                    .filter(has_text=_NIB_TUTUP_BUTTON)
                    .filter(visible=True)
                    .first
                )

                expect(close_button).to_be_visible(timeout=5000)
                expect(close_button).to_be_enabled(timeout=5000)

                self.click_locator(
                    close_button,
                    action_name="closing 'Segera Lengkapi NIB' blocker",
                    expected_text="Tutup",
                    timeout_ms=10000,
                    load_state=None,
                )
            except (PlaywrightError, AssertionError, TimeoutError) as exc:
                log_print(
                    "Tutup click on 'Segera Lengkapi NIB' did not complete "
                    "cleanly; verifying whether the modal closed anyway.",
                    exc,
                )
            finally:
                self._debug_interaction_checkpoint(
                    "nib_tutup_after_click",
                    target_name="NIB Tutup",
                    target_locator_factory=lambda: self._debug_nib_button_collection(
                        _NIB_TUTUP_BUTTON
                    ),
                )

            try:
                self.perbarui_data_nib_pelanggan_modal.wait_for(
                    state="hidden",
                    timeout=7000,
                )
                log_print("'Segera Lengkapi NIB' modal closed.")
                return True
            except TimeoutError:
                if attempt < _NIB_TUTUP_CLICK_ATTEMPTS:
                    log_print(
                        "'Segera Lengkapi NIB' is still visible after Tutup; "
                        "reacquiring the live button and retrying."
                    )
                    self.page.wait_for_timeout(500)

        return not self._is_visible(self.perbarui_data_nib_pelanggan_modal)

    def attempt_continue_perbarui_data_pelanggan(self) -> PerbaruiDataPelangganAction:
        """Compatibility alias for the NIB-only continue-later behavior."""
        return self.attempt_continue_perbarui_data_nib_pelanggan()

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
        except PlaywrightError, TypeError:
            log_print("Dashboard tile visibility probe failed", level="DEBUG")

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
            except PlaywrightError, TypeError:
                log_print(
                    "Dashboard navigation candidate was not usable", level="DEBUG"
                )
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
            .or_(self.transaction_blocker_alert)
            .or_(self._precheck_modal_locator())
        )

    def _precheck_modal_locator(self):
        return (
            self.pelanggan_tidak_terdaftar_modal.or_(
                self.registration_request_limited_modal
            )
            .or_(self.perbarui_data_nib_pelanggan_modal)
            .or_(self.perbarui_data_pelanggan_modal)
            .or_(self.invalid_registered_nik_modal)
            .or_(self.cannot_transact_at_base_modal)
            .or_(self.unusual_transaction_modal)
        )

    @staticmethod
    def _is_visible(locator) -> bool:
        try:
            try:
                return locator.is_visible(timeout=100)
            except TypeError:
                return locator.is_visible()
        except AttributeError, PlaywrightError:
            return False

    def _has_visible_dialog(self) -> bool:
        try:
            return self.page.locator("[role='dialog']:visible").count() > 0
        except PlaywrightError:
            return False

    def _has_visible_blocking_transaction_dialog(self) -> bool:
        """
        Compatibility guard used by is_transaction_form_ready().

        At this stage any visible dialog blocks interaction with the transaction
        form until the central modal handler resolves it.
        """
        return self._has_visible_dialog()

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
