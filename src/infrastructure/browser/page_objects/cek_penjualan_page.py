import re
from time import monotonic

from playwright.sync_api import Page

from src.application.models.transaction_outcome import TransactionOutcome
from src.infrastructure.browser.page_objects.base_page import BasePage
from src.infrastructure.browser.page_objects.penjualan_page import (
    TRANSACTION_BLOCKER_ALERT_RE,
    classify_transaction_blocker_text,
)
from src.infrastructure.browser.page_objects.update_success_modal import UpdateSuccessModal
from src.logging_utils import log_print

_CUSTOMER_DATA_REQUIRED_TITLE = re.compile(r"Terlalu\s+banyak\s+permintaan", re.IGNORECASE)
_CUSTOMER_DATA_REQUIRED_MESSAGE = re.compile(
    r"Terdapat\s+beberapa\s+data\s+yang\s+belum\s+lengkap\.\s*"
    r"Lengkapi\s+data\s+dahulu\s+untuk\s+melanjutkan\s+transaksi\.?",
    re.IGNORECASE,
)


class CekPenjualan(BasePage):
    def __init__(self, page: Page) -> None:
        super().__init__(page)
        self.proses_penjualan_button = page.get_by_role(
            "button", name="PROSES PENJUALAN"
        )
        self.kembali_button = page.get_by_role(
            "button", name="KEMBALI KE HALAMAN UTAMA"
        )
        # Title AND body identify the observed business rejection, not a generic
        # rate-limit warning. Reuse the application's visible-dialog convention.
        self.customer_data_required_modal = (
            page.get_by_role("dialog")
            .filter(has_text=_CUSTOMER_DATA_REQUIRED_TITLE)
            .filter(has_text=_CUSTOMER_DATA_REQUIRED_MESSAGE)
            .filter(visible=True)
            .first
        )
        self.zero_stock_modal = (
            page.get_by_role("dialog")
            .filter(has_text="Stok Tabung Kosong")
            .filter(visible=True)
            .first
        )
        self.transaction_blocker_alert = (
            page.locator("div.mantine-Text-root, span")
            .filter(has_text=TRANSACTION_BLOCKER_ALERT_RE)
            .filter(visible=True)
            .first
        )
        self.customer_update_success = UpdateSuccessModal(page)

    def wait_for_transaction_outcome(self, timeout_ms: int = 10_000) -> TransactionOutcome:
        """Wait for positive sale evidence or a known rejection; never submit."""
        deadline = monotonic() + timeout_ms / 1000
        while True:
            # Blockers take precedence over any stale success element underneath.
            if self.customer_data_required_modal.is_visible():
                return TransactionOutcome(
                    "blocked", "customer_data_required",
                    self.customer_data_required_modal.inner_text(timeout=1000).strip(),
                )
            if self.zero_stock_modal.is_visible():
                return TransactionOutcome("blocked", "zero_stock", "Stok Tabung Kosong")
            if self.transaction_blocker_alert.is_visible():
                text = self.transaction_blocker_alert.inner_text(timeout=1000).strip()
                kind = classify_transaction_blocker_text(text)
                if kind is not None:
                    return TransactionOutcome("blocked", kind, text)
            # This separate workflow uses the same return-home button; it is
            # positive evidence of a customer update, not of a sale.
            if self.customer_update_success.is_visible():
                return TransactionOutcome(
                    "unknown", "customer_update_result", "Data Pelanggan berhasil"
                )
            if self.kembali_button.is_visible():
                return TransactionOutcome(
                    "completed", evidence="KEMBALI KE HALAMAN UTAMA"
                )
            remaining_ms = (deadline - monotonic()) * 1000
            if remaining_ms <= 0:
                return TransactionOutcome("unknown", "confirmation_timeout")
            self.page.wait_for_timeout(min(100, remaining_ms))

    def proses_penjualan(self) -> None:
        self.click_button_and_wait(
            self.proses_penjualan_button,
            "PROSES PENJUALAN",
            timeout_ms=10000,
        )
        log_print("Proses Penjualan button clicked")

    def kembali_ke_dashboard(self) -> None:
        self.click_button_and_wait(
            self.kembali_button,
            "KEMBALI KE HALAMAN UTAMA",
            timeout_ms=10000,
        )
        log_print("Kembali ke Dashboard button clicked")
