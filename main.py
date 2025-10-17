from playwright.sync_api import sync_playwright

from src.config import Config
from src.web.pages.login import Login
from src.web.pages.dashboard import Dashboard


def main():
    config = Config()  # Load configuration

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=False)
        context = browser.new_context()  # Create a new browser context
        page = context.new_page()  # Open a new page

        print(config.url_application)  # Print the application URL for debugging
        page.goto(config.url_application)  # Navigate to the application URL

        login = Login(page)  # Initialize the Login page object
        login.login(config.email_user, config.pin_user)  # Perform login

        dashboard = Dashboard(page)  # Initialize the Dashboard page object
        profile_name = dashboard.get_profile_name()  # Retrieve profile name
        dashboard.assert_profile_name_is(profile_name)  # Assert profile name
        dashboard.catat_penjualan(config.nik)  # Click "Catat Penjualan" button
        page.wait_for_load_state("networkidle") # Wait for the page to load completely
        page.wait_for_timeout(5000)  # Wait for 5 seconds to observe the result
        browser.close() # Close the browser


if __name__ == "__main__":
    main()
