from playwright.sync_api import sync_playwright

from src.config import Config
from src.web.helpers import Helpers
from src.web.pages.cek_penjualan import CekPenjualan
from src.web.pages.dashboard import Dashboard
from src.web.pages.login import Login
from src.web.pages.penjualan import Penjualan
from src.web.rate_limiter import SkipRateLimiter
from src.web.reporter import TransactionReporter


def main():
    config = Config()
    reporter = TransactionReporter()

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

        # rate limiter
        limiter = SkipRateLimiter(
            max_skips=10, window_seconds=60, min_cooldown=60, jitter_seconds=5
        )

        # process each NIK
        for nik in config.nik:
            started_at = reporter.start_item(nik)
            try:
                # Back off if we recently hit too many skipped NIKs
                limiter.wait_if_needed(page)

                # go to "Catat Penjualan" for this NIK
                dashboard.catat_penjualan(
                    nik
                )  # ensure this method accepts a single nik
                page.wait_for_load_state("load")  # wait navigation/content

                # If the "Update Customer Data" modal appears, close and SKIP this NIK
                if dashboard.close_perbarui_data_pelanggan_if_needed():
                    limiter.record_skip()
                    reporter.skip_needs_update(nik, started_at, url=page.url)
                    print(f"Skipping NIK {nik} (needs data update).")
                    # Small pacing to reduce burstiness
                    page.wait_for_timeout(300)
                    continue

                # If the "not registered" modal appears, close and SKIP this NIK
                if dashboard.close_pelanggan_tidak_terdaftar_if_needed():
                    limiter.record_skip()
                    reporter.skip_not_registered(nik, started_at, url=page.url)
                    print(f"Skipping NIK {nik} (not registered).")
                    # Small pacing to reduce burstiness
                    page.wait_for_timeout(300)
                    continue

                # Proceed normally (this does not count against rate limit)
                # jenis pelanggan selection (if needed)
                dashboard.select_jenis_pelanggan_if_needed()

                # penjualan
                penjualan = Penjualan(page)
                # Check early: alert visible right after filling NIK
                if penjualan.is_max_kuota_alert_present(timeout=1500):
                    # Reset to NIK form for the next iteration and SKIP this NIK
                    try:
                        penjualan.ganti_pelanggan()
                    except Exception:
                        pass
                    limiter.record_skip()
                    reporter.skip_max_kuota(
                        nik,
                        started_at,
                        url=page.url,
                        reason="Max kuota before cek pesanan",
                    )
                    print(f"Skipping NIK {nik} (max kuota).")
                    page.wait_for_timeout(300)
                    continue

                # No alert yet, proceed to cek pesanan
                penjualan.cek_pesanan()

                # Check again: some apps show the alert only after CEK PESANAN
                if penjualan.is_max_kuota_alert_present(timeout=1500):
                    try:
                        penjualan.ganti_pelanggan()
                    except Exception:
                        pass
                    limiter.record_skip()
                    reporter.skip_max_kuota(
                        nik,
                        started_at,
                        url=page.url,
                        reason="Max kuota after cek pesanan",
                    )
                    print(f"Skipping NIK {nik} (max kuota after cek pesanan).")
                    page.wait_for_timeout(300)
                    continue

                # Only proceed if no alert at both checkpoints
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

                # record completion
                reporter.complete(nik, started_at, url=page.url)
            except Exception as e:
                print(f"Failed processing NIK {nik}: {e}")
                reporter.error(nik, started_at, e, url=page.url)

                # Only re-login if we truly got logged out
                is_logged_out = False
                try:
                    is_logged_out = (
                        "login" in page.url
                        or page.get_by_placeholder("Email").is_visible(timeout=800)
                        or page.get_by_role("button", name="MASUK").is_visible(
                            timeout=800
                        )
                    )
                except Exception:
                    pass

                if is_logged_out:
                    # Perform login recovery
                    page.goto(config.url_application)
                    login.login(config.email_user, config.pin_user)
                    page.wait_for_load_state("load")
                else:
                    # Stay in-session: try to recover to dashboard
                    try:
                        dashboard.ensure_on_dashboard()
                    except Exception:
                        page.goto(config.url_application)
                        # Do not login here; only if the app redirects to login you'll hit the block above on the next iteration.

        # end of NIK loop, close browser
        browser.close()

    # Report
    reporter.write_files()
    reporter.print_summary()


if __name__ == "__main__":
    main()
