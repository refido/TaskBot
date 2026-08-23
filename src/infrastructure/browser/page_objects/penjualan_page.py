import re
from typing import Literal

from playwright.sync_api import Page, TimeoutError

from src.infrastructure.browser.page_objects.base_page import BasePage
from src.logging_utils import log_print

TransactionBlockerKind = Literal["zero_stock", "max_kuota"]
TransactionBlockerAlert = tuple[TransactionBlockerKind, str]

_MAX_KUOTA_ALERT_PATTERN = (
    r"Tidak\s+dapat\s+transaksi\s+karena\s+telah\s+melebihi\s+batas\s+"
    r"kewajaran\s+pembelian\s+LPG\s+3\s*kg\s+bulan\s+ini\.?"
)
_ZERO_STOCK_ALERT_PATTERN = (
    r"tidak\s+dapat\s+transaksi.*stok\s+tabung.*(?:kosong|\b0\b)"
)
MAX_KUOTA_ALERT_RE = re.compile(
    rf"^\s*{_MAX_KUOTA_ALERT_PATTERN}\s*$",
    re.IGNORECASE | re.DOTALL,
)
ZERO_STOCK_ALERT_RE = re.compile(
    _ZERO_STOCK_ALERT_PATTERN,
    re.IGNORECASE | re.DOTALL,
)
TRANSACTION_BLOCKER_ALERT_RE = re.compile(
    rf"(?:^\s*{_MAX_KUOTA_ALERT_PATTERN}\s*$|{_ZERO_STOCK_ALERT_PATTERN})",
    re.IGNORECASE | re.DOTALL,
)


def classify_transaction_blocker_text(text: str) -> TransactionBlockerKind | None:
    """Classify only known transaction-blocking messages."""
    normalized_text = " ".join(text.split())
    if ZERO_STOCK_ALERT_RE.search(normalized_text):
        return "zero_stock"
    if MAX_KUOTA_ALERT_RE.search(normalized_text):
        return "max_kuota"
    return None


class Penjualan(BasePage):
    def __init__(self, page: Page) -> None:
        super().__init__(page)
        self.cek_pesanan_button = page.get_by_role("button", name="CEK PESANAN")
        self.cek_max_kuota_alert = (
            page.locator("div.mantine-Text-root:visible")
            .filter(has_text=MAX_KUOTA_ALERT_RE)
            .first
        )
        self.transaction_blocker_alert = page.locator(
            ".styles_alertInfo__WvEN4 .styles_content__fqQml > "
            "span:nth-child(1):visible, div.mantine-Text-root:visible"
        ).filter(has_text=TRANSACTION_BLOCKER_ALERT_RE)
        self.zero_stock_alert_text = page.locator(
            ".styles_alertInfo__WvEN4 .styles_content__fqQml > span:nth-child(1)"
        )
        self.ganti_pelanggan_button = page.get_by_role("button", name="Ganti Pelanggan")

    def cek_pesanan(self) -> None:
        self.click_button_and_wait(self.cek_pesanan_button, "CEK PESANAN")
        log_print("Cek Pesanan button clicked")

    def read_transaction_blocker_alert(
        self, timeout: int = 1500
    ) -> TransactionBlockerAlert | None:
        try:
            self.transaction_blocker_alert.first.wait_for(
                state="visible", timeout=timeout
            )
        except TimeoutError:
            log_print("Transaction blocker alert not present")
            return None

        text = self.transaction_blocker_alert.first.inner_text().strip()
        if not text:
            text = "Tidak dapat transaksi"
            log_print("Transaction blocker alert is visible but empty")

        alert_kind = classify_transaction_blocker_text(text)
        if alert_kind is None:
            log_print(
                "Unknown transaction blocker alert ignored:",
                text,
                level="WARNING",
                event="transaction.blocker.unknown",
            )
            return None

        log_print(
            "Transaction blocker alert detected:",
            alert_kind,
            event="transaction.blocker.detected",
            blocker_kind=alert_kind,
            alert_text=text,
        )
        return (alert_kind, text)

    def is_max_kuota_alert_present(self, timeout: int = 1500) -> bool:
        try:
            self.cek_max_kuota_alert.wait_for(state="visible", timeout=timeout)
            log_print("Max kuota alert detected")
            return True
        except TimeoutError:
            log_print("Max kuota alert not present")
            return False

    def get_zero_stock_alert_text(self, timeout: int = 1500) -> str | None:
        try:
            self.zero_stock_alert_text.wait_for(state="visible", timeout=timeout)
        except TimeoutError:
            log_print("Zero stock alert text not present")
            return None

        text = self.zero_stock_alert_text.inner_text().strip()
        if not text:
            log_print("Zero stock alert locator is visible but empty")
            return None

        log_print("Zero stock alert text extracted:", text)
        return text

    def is_zero_stock_alert_text(self, text: str) -> bool:
        normalized_text = " ".join(text.split())
        if ZERO_STOCK_ALERT_RE.search(normalized_text):
            log_print("Zero stock alert detected")
            return True

        log_print("Zero stock alert text did not match:", normalized_text)
        return False

    def ganti_pelanggan(self) -> None:
        self.click_button_and_wait(self.ganti_pelanggan_button, "Ganti Pelanggan")
        log_print("Ganti Pelanggan button clicked")
