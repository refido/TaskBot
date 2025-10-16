import os

from dotenv import load_dotenv


class Config:
    def __init__(self):
        load_dotenv()
        self.url_application = os.getenv("URL_APPlICATION")
        self.email_user: str = os.getenv("EMAIL")
        self.pin_user: str = os.getenv("PIN")
