from playwright.sync_api import sync_playwright

from src.config import Config
from src.web.helpers import Helpers
from src.web.pages.cek_penjualan import CekPenjualan
from src.web.pages.dashboard import Dashboard
from src.web.pages.login import Login
from src.web.pages.penjualan import Penjualan


def main():
    config = Config()

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=False)  # start browser
        context = browser.new_context()  # single session for all NIKs
        page = context.new_page()  # open a page

        print(config.url_application)
        page.goto(config.url_application)  # navigate to app
        # login
        login = Login(page)
        login.login(config.email_user, config.pin_user)
        page.wait_for_load_state("load")  # wait for page load

        # dashboard
        dashboard = Dashboard(page)
        profile_name = dashboard.get_profile_name()
        dashboard.assert_profile_name_is(profile_name)
        dashboard.get_current_stock()

        # process each NIK
        for nik in config.nik:
            try:
                # go to "Catat Penjualan" for this NIK
                dashboard.catat_penjualan(
                    nik
                )  # ensure this method accepts a single nik
                page.wait_for_load_state("load")  # wait navigation/content

                # jenis pelanggan selection (if needed)
                dashboard.select_jenis_pelanggan_if_needed()

                # penjualan
                penjualan = Penjualan(page)
                penjualan.cek_pesanan()

                # cek penjualan
                cek_penjualan = CekPenjualan(page)
                cek_penjualan.proses_penjualan()

                # wait for manual confirmation
                helpers = Helpers(page)
                helpers.wait_for_human_interaction()

                cek_penjualan.kembali_ke_dashboard()
                page.wait_for_load_state("load")  # back at dashboard

                # optional: check stock after each NIK
                dashboard.get_current_stock()
            except Exception as e:
                print(f"Failed processing NIK {nik}: {e}")
                # Optionally navigate back to dashboard to recover
                page.goto(config.url_application)
                login.login(config.email_user, config.pin_user)
                page.wait_for_load_state("load")

        browser.close()


if __name__ == "__main__":
    main()
