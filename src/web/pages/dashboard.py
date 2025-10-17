from playwright.sync_api import Page, expect


class Dashboard:
    def __init__(self, page: Page):
        self.page = page
        self.profile_name = page.locator(
            "#__next .styles_wrapper__ASq0Q .mantine-Text-root"
        ).first

        self.catat_penjualan_tile = page.get_by_text(
            "Catat Penjualan", exact=True
        ).first

        self.nik_input = page.get_by_placeholder("Masukkan 16 digit NIK Pelanggan", exact=True)

        self.lanjutkan_penjualan_button = page.get_by_role(
            "button", name="LANJUTKAN PENJUALAN"
        )

    def get_profile_name(self) -> str:
        expect(self.profile_name).to_be_visible(timeout=10000)
        name = self.profile_name.inner_text()
        print("Profile name retrieved:", name)
        return name

    def assert_profile_name_is(self, expected_name: str):
        expect(self.profile_name).to_be_visible(timeout=10000)
        expect(self.profile_name).to_have_text(expected_name, timeout=10000)

    def catat_penjualan(self, nik: str):
        tile = self.catat_penjualan_tile
        expect(tile).to_be_visible(timeout=10000)
        text = tile.inner_text()
        print('Clicking tile name:', text)
        expect(tile).to_contain_text("Catat Penjualan")
        tile.click()
        self.page.wait_for_load_state("networkidle")
        expect(self.nik_input).to_be_visible(timeout=10000)
        self.nik_input.click()
        self.nik_input.fill("")
        self.nik_input.type(str(nik), delay=20)
        print("NIK input filled with:", nik)
        expect(self.lanjutkan_penjualan_button).to_be_enabled(timeout=10000)
        self.lanjutkan_penjualan_button.click()
        print("Lanjutkan Penjualan button clicked")


