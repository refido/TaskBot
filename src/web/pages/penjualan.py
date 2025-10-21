import re

from playwright.sync_api import Page, expect


class Penjualan:
    def __init__(self, page: Page):
        self.page = page
        self.cek_pesanan_button = page.get_by_role("button", name="CEK PESANAN")

        # Robust text-based locator (ignores spacing/newlines)
        self.cek_max_kuota_alert = page.locator("div.mantine-Text-root").filter(
            has_text=re.compile(r"Tidak\s+dapat\s+transaksi", re.I | re.S)
        )

        self.ganti_pelanggan_button = page.get_by_role("button", name="Ganti Pelanggan")

    def cek_pesanan(self):
        button = self.cek_pesanan_button  # Replace with the actual locator
        expect(button).to_be_enabled(timeout=5000)  # Wait for the button to be enabled
        text = button.inner_text()  # Get the button text
        print("Clicking button name:", text)  # Print the button name
        expect(button).to_contain_text("CEK PESANAN")  # Assert the button text
        button.click()  # Click the button
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        print("Cek Pesanan button clicked")  # Print confirmation

    def is_max_kuota_alert_present(self, timeout: int = 1500) -> bool:
        print(self.page.locator("div.mantine-Text-root").all_text_contents())
        try:
            self.cek_max_kuota_alert.wait_for(state="visible", timeout=timeout)
            print("Max kuota alert detected")
            return True
        except Exception:
            print("Max kuota alert not present")
            return False

    def ganti_pelanggan(self):
        button = self.ganti_pelanggan_button  # Replace with the actual locator
        expect(button).to_be_enabled(timeout=5000)  # Wait for the button to be enabled
        text = button.inner_text()  # Get the button text
        print("Clicking button name:", text)  # Print the button name
        expect(button).to_contain_text("Ganti Pelanggan")  # Assert the button text
        button.click()  # Click the button
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        print("Ganti Pelanggan button clicked")  # Print confirmation
