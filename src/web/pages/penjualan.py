import re

from playwright.sync_api import Page

from src.logging_utils import log_print
from src.web.pages.base_page import BasePage


class Penjualan(BasePage):
    def __init__(self, page: Page) -> None:
        super().__init__(page)
        self.cek_pesanan_button = page.get_by_role("button", name="CEK PESANAN")

        # Robust text-based locator (ignores spacing/newlines)
        self.cek_max_kuota_alert = page.locator("div.mantine-Text-root").filter(
            has_text=re.compile(r"Tidak\s+dapat\s+transaksi", re.I | re.S)
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

    def ganti_pelanggan(self) -> None:
        self.click_button_and_wait(self.ganti_pelanggan_button, "Ganti Pelanggan")
        log_print("Ganti Pelanggan button clicked")
