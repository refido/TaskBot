from playwright.sync_api import Page, TimeoutError, expect


class Dashboard:
    def __init__(self, page: Page):
        self.page = page
        self.profile_name = page.locator(
            "#__next .styles_wrapper__ASq0Q .mantine-Text-root"
        ).first

        self.current_stock = page.get_by_text("Tabung").first

        self.catat_penjualan_tile = page.get_by_text(
            "Catat Penjualan", exact=True
        ).first

        self.nik_input = page.get_by_placeholder(
            "Masukkan 16 digit NIK Pelanggan", exact=True
        )

        self.lanjutkan_penjualan_button = page.get_by_role(
            "button", name="LANJUTKAN PENJUALAN"
        )

        self.jenis_pelanggan = page.get_by_text("Rumah Tangga", exact=True)
        self.lanjut_transaksi_button = page.get_by_text("LANJUTKAN TRANSAKSI")

        # Modal-scoped locators
        self.jenis_pelanggan_modal = page.get_by_role("dialog").filter(
            has_text="Jenis Pelanggan"
        )
        self.jenis_pelanggan = self.jenis_pelanggan_modal.get_by_text(
            "Rumah Tangga", exact=True
        )
        self.lanjut_transaksi_button = self.jenis_pelanggan_modal.get_by_role(
            "button", name="LANJUTKAN TRANSAKSI"
        )

    def get_profile_name(self) -> str:
        expect(self.profile_name).to_be_visible(timeout=10000)
        name = self.profile_name.inner_text()
        print("Profile name retrieved:", name)
        return name

    def assert_profile_name_is(self, expected_name: str):
        expect(self.profile_name).to_be_visible(timeout=10000)
        expect(self.profile_name).to_have_text(expected_name, timeout=10000)

    def get_current_stock(self) -> str:
        expect(self.current_stock).to_be_visible(timeout=10000)
        stock = self.current_stock.inner_text()
        print("Current stock retrieved:", stock)
        return stock

    def catat_penjualan(self, nik: str):
        tile = self.catat_penjualan_tile  # Replace with the actual locator
        expect(tile).to_be_visible(timeout=10000)  # Wait for the tile to be visible
        text = tile.inner_text()  # Get the text of the tile
        print("Clicking tile name:", text)  # Print the tile name
        expect(tile).to_contain_text("Catat Penjualan")  # Assert the tile text
        tile.click()  # Click the tile
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        expect(self.nik_input).to_be_visible(
            timeout=10000
        )  # Wait for NIK input to be visible
        self.nik_input.click()  # Click the NIK input
        self.nik_input.fill("")  # Clear the NIK input
        self.nik_input.type(str(nik), delay=20)  # Type the NIK
        print("NIK input filled with:", nik)  # Print the filled NIK
        expect(self.lanjutkan_penjualan_button).to_be_enabled(
            timeout=10000
        )  # Wait for the button to be enabled
        text = self.lanjutkan_penjualan_button.inner_text()  # Get the button text
        print("Clicking button name:", text)  # Print the button name
        expect(self.lanjutkan_penjualan_button).to_contain_text(
            "LANJUTKAN PENJUALAN"
        )  # Assert the button text
        self.lanjutkan_penjualan_button.click()  # Click the button
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        print("Lanjutkan Penjualan button clicked")  # Print confirmation

    # Only run if the modal actually appears
    def select_jenis_pelanggan_if_needed(self, detect_timeout: int = 2000) -> bool:
        try:
            self.jenis_pelanggan_modal.wait_for(state="visible", timeout=detect_timeout)
        except TimeoutError as e:
            print("Jenis Pelanggan modal not present; skipping.", e)
            return False

        self.select_jenis_pelanggan()
        return True

    def select_jenis_pelanggan(self):
        # Assumes modal is visible (gated by select_jenis_pelanggan_if_needed)
        radio_button = self.jenis_pelanggan
        expect(radio_button).to_be_visible(
            timeout=10000
        )  # Wait for the radio button to be visible
        expect(radio_button).to_be_enabled(
            timeout=10000
        )  # Wait for the radio button to be enabled
        text = radio_button.inner_text()  # Get the radio button text
        print("Clicking radio_button name:", text)  # Print the radio button name
        expect(radio_button).to_contain_text(
            "Rumah Tangga"
        )  # Assert the radio button text
        radio_button.click()  # Click the radio button
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        print("Jenis Pelanggan radio_button clicked")  # Print confirmation

        # Button is modal-scoped; assert presence/enabled then click
        expect(self.lanjut_transaksi_button).to_be_visible(
            timeout=10000
        )  # Wait for the button to be visible
        expect(self.lanjut_transaksi_button).to_be_enabled(
            timeout=10000
        )  # Wait for the button to be enabled
        text = self.lanjut_transaksi_button.inner_text()  # Get the button text
        print("Clicking button name:", text)  # Print the button name
        expect(self.lanjut_transaksi_button).to_contain_text(
            "LANJUTKAN TRANSAKSI"
        )  # Assert the button text
        self.lanjut_transaksi_button.click()  # Click the button
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        print("Lanjutkan Transaksi button clicked")  # Print confirmation
