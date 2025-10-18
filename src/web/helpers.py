from playwright.sync_api import Page


class Helpers:
    def __init__(self, page: Page):
        self.page = page

    def wait_for_human_interaction(self, timeout: int = 5000):
        print("Waiting for human interaction...")
        self.page.wait_for_timeout(timeout)
