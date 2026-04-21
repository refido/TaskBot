import re

from playwright.sync_api import Page

from src.infrastructure.browser.page_objects.base_page import BasePage
from src.logging_utils import log_print


class Penjualan(BasePage):
    _ZERO_STOCK_ALERT_RE = re.compile(
        r"tidak\s+dapat\s+transaksi.*stok\s+tabung.*(?:kosong|\b0\b)",
        re.I | re.S,
    )

    def __init__(self, page: Page) -> None:
        super().__init__(page)
        self.cek_pesanan_button = page.get_by_role("button", name="CEK PESANAN")
        self.cek_max_kuota_alert = page.locator("div.mantine-Text-root").filter(
            has_text=re.compile(r"Tidak\s+dapat\s+transaksi", re.I | re.S)
        )
        self.zero_stock_alert_text = page.locator(
            ".styles_alertInfo__WvEN4 .styles_content__fqQml > span:nth-child(1)"
        )
        self.ganti_pelanggan_button = page.get_by_role("button", name="Ganti Pelanggan")

    def cek_pesanan(self) -> None:
        self.click_button_and_wait(self.cek_pesanan_button, "CEK PESANAN")
        log_print("Cek Pesanan button clicked")

    def is_max_kuota_alert_present(self, timeout: int = 1500) -> bool:
        log_print(self.page.locator("div.mantine-Text-root").all_text_contents())
        try:
            self.cek_max_kuota_alert.wait_for(state="visible", timeout=timeout)
            log_print("Max kuota alert detected")
            return True
        except Exception:
            log_print("Max kuota alert not present")
            return False

    def get_zero_stock_alert_text(self, timeout: int = 1500) -> str | None:
        try:
            self.zero_stock_alert_text.wait_for(state="visible", timeout=timeout)
        except Exception:
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
        if self._ZERO_STOCK_ALERT_RE.search(normalized_text):
            log_print("Zero stock alert detected")
            return True

        log_print("Zero stock alert text did not match:", normalized_text)
        return False

    def ganti_pelanggan(self) -> None:
        self.click_button_and_wait(self.ganti_pelanggan_button, "Ganti Pelanggan")
        log_print("Ganti Pelanggan button clicked")
