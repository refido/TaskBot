import re

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

        # Pelanggan Tidak Terdaftar modal (unique button var)
        self.pelanggan_tidak_terdaftar_modal = page.get_by_role("dialog").filter(
            has=self.page.get_by_text("Pelanggan Tidak Terdaftar")
        )
        self.pelanggan_tidak_terdaftar_tutup = (
            self.pelanggan_tidak_terdaftar_modal.get_by_role("button").filter(
                has_text=re.compile(r"^\s*tutup\s*$", re.I)
            )
        )

        # Perbarui Data Pelanggan modal (use :has instead of has_text)
        self.perbarui_data_pelanggan_modal = page.locator(
            'section[role="dialog"]:has(.mantine-Text-root:has-text("Perbarui Data Pelanggan"))'
        )
        self.perbarui_data_pelanggan_tutup = (
            self.perbarui_data_pelanggan_modal.get_by_role("button").filter(
                has_text=re.compile(r"^\s*tutup\s*$", re.I)
            )
        )

    def get_profile_name(self) -> str:
        expect(self.profile_name).to_be_visible(timeout=5000)
        name = self.profile_name.inner_text()
        print("Profile name retrieved:", name)
        return name

    def assert_profile_name_is(self, expected_name: str):
        expect(self.profile_name).to_be_visible(timeout=5000)
        expect(self.profile_name).to_have_text(expected_name, timeout=5000)

    def get_current_stock(self) -> str:
        expect(self.current_stock).to_be_visible(timeout=5000)
        stock = self.current_stock.inner_text()
        print("Current stock retrieved:", stock)
        return stock

    def catat_penjualan(self, nik: str):
        # If the NIK input is already visible, skip clicking the tile
        already_on_form = False
        try:
            self.nik_input.wait_for(state="visible", timeout=800)
            already_on_form = True
            print("NIK input already visible; skipping tile click")
        except Exception:
            pass

        if not already_on_form:
            tile = self.catat_penjualan_tile
            expect(tile).to_be_visible(timeout=5000)
            text = tile.inner_text()
            print("Clicking tile name:", text)
            expect(tile).to_contain_text("Catat Penjualan")
            tile.click()
            self.page.wait_for_load_state("networkidle")
            expect(self.nik_input).to_be_visible(timeout=5000)

        # Only the input-and-continue steps
        self.nik_input.click()  # Focus the input
        self.nik_input.fill("")  # Clear any existing text
        self.nik_input.type(str(nik), delay=20)  # Type with slight delay
        print("NIK input filled with:", nik)

        expect(self.lanjutkan_penjualan_button).to_be_enabled(timeout=5000)
        text = self.lanjutkan_penjualan_button.inner_text()  # Get the button text
        print("Clicking button name:", text)
        expect(self.lanjutkan_penjualan_button).to_contain_text("LANJUTKAN PENJUALAN")
        self.lanjutkan_penjualan_button.click()
        self.page.wait_for_load_state("networkidle")
        print("Lanjutkan Penjualan button clicked")

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

    # Only run if the "Pelanggan Tidak Terdaftar" modal appears
    def close_pelanggan_tidak_terdaftar_if_needed(
        self, detect_timeout: int = 6000
    ) -> bool:
        try:
            self.pelanggan_tidak_terdaftar_modal.wait_for(
                state="visible", timeout=detect_timeout
            )
        except TimeoutError:
            print("Pelanggan Tidak Terdaftar modal not present; continuing.")
            return False

        expect(self.pelanggan_tidak_terdaftar_tutup).to_be_visible(timeout=5000)
        expect(self.pelanggan_tidak_terdaftar_tutup).to_be_enabled(timeout=5000)
        self.pelanggan_tidak_terdaftar_tutup.click()
        self.pelanggan_tidak_terdaftar_modal.wait_for(state="hidden", timeout=7000)

        try:
            expect(self.nik_input).to_be_visible(timeout=3000)
            self.nik_input.fill("")
            print("Closed 'Pelanggan Tidak Terdaftar'; NIK input reset.")
        except TimeoutError:
            self.ensure_on_dashboard()
            print("Closed 'Pelanggan Tidak Terdaftar'; returned to dashboard.")
        return True

    def close_pelanggan_tidak_terdaftar_modal(self):
        expect(self.tutup_button).to_be_visible(
            timeout=5000
        )  # Wait for the button to be visible
        expect(self.tutup_button).to_be_enabled(
            timeout=5000
        )  # Wait for the button to be enabled
        text = self.tutup_button.inner_text()  # Get the button text
        print("Clicking button name:", text)  # Print the button name
        expect(self.tutup_button).to_contain_text("TUTUP")  # Assert the button text
        self.tutup_button.click()  # Click the button
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        print("Tutup button clicked")  # Print confirmation

    def ensure_on_dashboard(self):
        """
        Make sure we are back at dashboard where 'Catat Penjualan' tile is visible.
        Tries a few lightweight recovery actions before asserting.
        """
        try:
            if self.catat_penjualan_tile.is_visible(timeout=800):
                return
        except Exception:
            pass

        # Try common back actions without throwing
        for candidate in [
            self.page.get_by_role("button", name="KEMBALI"),
            self.page.get_by_role("link", name="Beranda"),
            self.page.get_by_role("link", name="Dashboard"),
            self.page.get_by_role("button", name="TUTUP"),
        ]:
            try:
                candidate.click(timeout=700)
                break
            except Exception:
                continue

        # Assert we're on dashboard
        expect(self.catat_penjualan_tile).to_be_visible(timeout=8000)

    def close_perbarui_data_pelanggan_if_needed(
        self, detect_timeout: int = 6000
    ) -> bool:
        try:
            self.perbarui_data_pelanggan_modal.wait_for(
                state="visible", timeout=detect_timeout
            )
        except TimeoutError:
            print("Perbarui Data Pelanggan modal not present; continuing.")
            return False

        expect(self.perbarui_data_pelanggan_tutup).to_be_visible(timeout=5000)
        expect(self.perbarui_data_pelanggan_tutup).to_be_enabled(timeout=5000)
        self.perbarui_data_pelanggan_tutup.click()
        self.perbarui_data_pelanggan_modal.wait_for(state="hidden", timeout=7000)

        # Stay on NIK screen if possible
        try:
            expect(self.nik_input).to_be_visible(timeout=3000)
            self.nik_input.fill("")
            print("Closed 'Perbarui Data Pelanggan'; NIK input reset.")
        except TimeoutError:
            self.ensure_on_dashboard()
            print("Closed 'Perbarui Data Pelanggan'; returned to dashboard.")
        return True

    def close_perbarui_data_pelanggan_modal(self):
        expect(self.tutup_button).to_be_visible(
            timeout=10000
        )  # Wait for the button to be visible
        expect(self.tutup_button).to_be_enabled(
            timeout=10000
        )  # Wait for the button to be enabled
        text = self.tutup_button.inner_text()  # Get the button text
        print("Clicking button name:", text)  # Print the button name
        expect(self.tutup_button).to_contain_text("TUTUP")  # Assert the button text
        self.tutup_button.click()  # Click the button
        self.page.wait_for_load_state(
            "networkidle"
        )  # Wait for the page to load completely
        print("Tutup button clicked")  # Print confirmation
