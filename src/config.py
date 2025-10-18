import os
from typing import List

from dotenv import load_dotenv


class Config:
    def __init__(self):
        load_dotenv()  # reads .env into environment variables [web:1]
        self.url_application: str = os.getenv("URL_APPLICATION", "")  # fix key name
        self.email_user: str = os.getenv("EMAIL", "")  # read email
        self.pin_user: str = os.getenv("PIN", "")  # read pin
        raw_nik = os.getenv("NIK", "")  # e.g. "1234567890123456"
        self.nik: List[int] = [
            int(n.strip()) for n in raw_nik.split(",") if n.strip()
        ]  # split and convert to ints
