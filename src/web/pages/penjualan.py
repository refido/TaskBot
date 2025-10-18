from playwright.sync_api import Page, expect


class Penjualan:
    def __init__(self, page: Page):
        self.page = page
        self.cek_pesanan_button = page.get_by_role("button", name="CEK PESANAN")

    def cek_pesanan(self):
        button = self.cek_pesanan_button  # Replace with the actual locator
        expect(button).to_be_enabled(timeout=10000)  # Wait for the button to be enabled
        text = button.inner_text()  # Get the button text
        print("Clicking button name:", text)  # Print the button name
        expect(button).to_contain_text("CEK PESANAN")  # Assert the button text
        button.click()  # Click the button
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        print("Cek Pesanan button clicked")  # Print confirmation
