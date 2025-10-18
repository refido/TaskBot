from playwright.sync_api import Page, expect


class CekPenjualan:
    def __init__(self, page: Page):
        self.page = page
        self.cek_pesanan_button = page.get_by_role("button", name="PROSES PENJUALAN")
        self.kembali_button = page.get_by_role(
            "button", name="KEMBALI KE HALAMAN UTAMA"
        )

    def proses_penjualan(self):
        button = self.cek_pesanan_button  # Replace with the actual locator
        expect(button).to_be_enabled(timeout=10000)  # Wait for the button to be enabled
        text = button.inner_text()  # Get the button text
        print("Clicking button name:", text)  # Print the button name
        expect(button).to_contain_text("PROSES PENJUALAN")  # Assert the button text
        button.click()  # Click the button
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        print("Proses Penjualan button clicked")  # Print confirmation

    def kembali_ke_dashboard(self):
        button = self.kembali_button  # Replace with the actual locator
        expect(button).to_be_enabled(timeout=10000)  # Wait for the button to be enabled
        text = button.inner_text()  # Get the button text
        print("Clicking button name:", text)  # Print the button name
        expect(button).to_contain_text(
            "KEMBALI KE HALAMAN UTAMA"
        )  # Assert the button text
        button.click()  # Click the button
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        print("Kembali ke Dashboard button clicked")  # Print confirmation
