from playwright.sync_api import Page, expect


class Login:
    def __init__(self, page: Page):
        self.page = page
        self.email = page.locator(
            'div.mantine-TextInput-root:has(label:has-text("Email")) input'
        )
        self.pin = page.locator(
            'div.mantine-TextInput-root:has(label:has-text("PIN")) input'
        )
        self.sign_in = page.get_by_role("button", name="Masuk")

    def login(self, email_user: str, pin_user: str):
        expect(self.email).to_be_visible(timeout=10000)
        self.email.click()
        self.email.fill("")  # clear safely
        self.email.type(str(email_user), delay=20)
        print("Email filled", email_user)

        expect(self.pin).to_be_visible(timeout=10000)
        self.pin.click()
        self.pin.fill("")
        self.pin.type(str(pin_user), delay=20)
        print("PIN filled", pin_user)

        expect(self.sign_in).to_be_enabled()
        self.sign_in.click()
        print("Masuk button clicked")
        self.page.wait_for_load_state("networkidle")
