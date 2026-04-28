from playwright.sync_api import Page

from src.infrastructure.browser.page_objects.base_page import BasePage
from src.logging_utils import log_print


class CekPenjualan(BasePage):
    def __init__(self, page: Page) -> None:
        super().__init__(page)
        self.proses_penjualan_button = page.get_by_role(
            "button", name="PROSES PENJUALAN"
        )
        self.kembali_button = page.get_by_role(
            "button", name="KEMBALI KE HALAMAN UTAMA"
        )

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
