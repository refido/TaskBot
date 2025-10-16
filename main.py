from playwright.sync_api import sync_playwright

from config import Config
from src.web.pages.login import Login


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

        browser.close()


if __name__ == "__main__":
    main()
