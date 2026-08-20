import re
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

        self.jenis_pelanggan_modal = (
            page.get_by_role("dialog")
            .filter(
                has_text=re.compile(
                    r"Jenis\s+Pelanggan|"
                    r"Pelanggan\s+Terdaftar|"
                    r"pilihan\s+jenis\s+pelanggan",
                    re.IGNORECASE,
                )
            )
            .first
        )

        self.jenis_pelanggan_lanjutkan_penjualan_button = (
            self.jenis_pelanggan_modal.get_by_role(
                "button",
                name=re.compile(
                    r"^\s*LANJUTKAN\s+PENJUALAN\s*$",
                    re.IGNORECASE,
                ),
            ).first
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
        registration_request_limited_message = page.locator(
            "div.mantine-Text-root"
        ).filter(has_text=_REGISTRATION_REQUEST_LIMITED_MESSAGE_EXACT).filter(
            visible=True
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
            self.registration_request_limited_modal.locator(
                "h1, h2, h3, h4, h5, h6"
            )
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

        self.perbarui_data_nib_pelanggan_modal = (
            page.locator('section[role="dialog"]')
            .filter(has_text=_PERBARUI_DATA_NIB_PELANGGAN_MESSAGE)
            .first
        )

        self.perbarui_data_nib_pelanggan_lanjut_nanti = (
            self.perbarui_data_nib_pelanggan_modal.get_by_role(
                "button",
                name=re.compile(
                    r"^\s*nanti saja,\s*lanjut (?:penjualan|transaksi)\s*$",
                    re.IGNORECASE,
                ),
            ).first
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
        except (PlaywrightError, AssertionError):
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
        except (PlaywrightError, AssertionError):
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

        Selection policy:
        1. Rumah Tangga
        2. Usaha Mikro
        3. First visible/enabled generic radio as fallback
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

        # Important:
        # Once we attempt this click, DO NOT try another customer type.
        # The click might succeed even if the UI is slow afterward.
        try:
            choice.click(timeout=15000)
        except PlaywrightError as exc:
            raise RuntimeError(
                f"Failed to click Jenis Pelanggan option '{option_name}'."
            ) from exc

        log_print(f"Jenis Pelanggan option clicked: {option_name}")

        # Wait for selection to propagate to the UI.
        continue_button = self._find_jenis_pelanggan_continue_button()

        if continue_button is None:
            raise RuntimeError(
                "Jenis Pelanggan option was clicked, but "
                "LANJUTKAN PENJUALAN button could not be found."
            )

        try:
            expect(continue_button).to_be_visible(timeout=15000)

            expect(continue_button).to_be_enabled(timeout=15000)

        except AssertionError as exc:
            raise RuntimeError(
                "LANJUTKAN PENJUALAN button did not become "
                "visible and enabled after selecting customer type."
            ) from exc

        log_print("Jenis Pelanggan selection accepted; LANJUTKAN PENJUALAN is enabled.")

        # Click only once.
        try:
            continue_button.click(timeout=15000)
        except PlaywrightError as exc:
            raise RuntimeError(
                "Failed to click LANJUTKAN PENJUALAN from Jenis Pelanggan modal."
            ) from exc

        log_print("Lanjutkan Penjualan button clicked from Jenis Pelanggan modal")

        # The customer-type modal should disappear after successful continue.
        try:
            self.jenis_pelanggan_modal.wait_for(
                state="hidden",
                timeout=7000,
            )
        except TimeoutError:
            # Don't immediately click again.
            #
            # The action may already have succeeded and the application
            # may simply be slow transitioning to the next state.
            log_print(
                "Jenis Pelanggan modal did not disappear immediately "
                "after LANJUTKAN PENJUALAN; continuing state detection."
            )

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

    def _find_named_customer_type_choice(
        self,
        option_name: str,
    ) -> Locator | None:
        """
        Locate a known customer type through semantic selectors.

        Try:
        1. accessible radio
        2. visible label
        3. visible text

        No generated CSS-module classes are used.
        """

        scope = self.jenis_pelanggan_modal

        option_pattern = re.compile(
            rf"^\s*{re.escape(option_name)}\s*$",
            re.IGNORECASE,
        )

        candidates = (
            scope.get_by_role(
                "radio",
                name=option_pattern,
            ),
            scope.locator("label").filter(has_text=option_pattern),
            scope.get_by_text(
                option_pattern,
            ),
        )

        for collection in candidates:
            choice = self._first_usable_locator(collection)

            if choice is not None:
                return choice

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
        Locate LANJUTKAN PENJUALAN inside the customer-type modal.

        Semantic role is primary. Plain button text is a fallback.
        """

        scope = self.jenis_pelanggan_modal

        button_pattern = re.compile(
            r"^\s*LANJUTKAN\s+PENJUALAN\s*$",
            re.IGNORECASE,
        )

        candidates = (
            scope.get_by_role(
                "button",
                name=button_pattern,
            ),
            scope.locator("button").filter(has_text=button_pattern),
        )

        for collection in candidates:
            button = self._first_usable_locator(
                collection,
                require_enabled=False,
            )

            if button is not None:
                return button

        return None

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
        self.click_locator(
            self.perbarui_data_nib_pelanggan_lanjut_nanti,
            action_name="continuing past Perbarui Data NIB Pelanggan modal",
            timeout_ms=5000,
            load_state=None,
        )
        log_print(
            "Clicked 'NANTI SAJA, LANJUT PENJUALAN' on the NIB reminder; "
            "continuing state detection."
        )

    def attempt_continue_perbarui_data_nib_pelanggan(
        self,
    ) -> PerbaruiDataPelangganAction:
        if not self.detect_perbarui_data_nib_pelanggan_if_needed():
            return "not_present"

        try:
            self.continue_perbarui_data_nib_pelanggan()
            return "continued"
        except TimeoutError, AssertionError:
            log_print("Continue-transaction button on the NIB reminder was not usable.")
            return "close"
        except Exception as exc:  # noqa: BLE001 - compatibility result distinguishes failure.
            log_print("Failed to continue past the NIB reminder.", exc)
            return "cannot_continue"

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
        except (PlaywrightError, TypeError):
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
            except (PlaywrightError, TypeError):
                log_print("Dashboard navigation candidate was not usable", level="DEBUG")
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
        except (AttributeError, PlaywrightError):
            return False

    def _has_visible_dialog(self) -> bool:
        try:
            return self.page.locator("[role='dialog']:visible").count() > 0
        except PlaywrightError:
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
