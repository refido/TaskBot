import base64
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


class Helpers:
    def __init__(self, page: Page):
        self.page = page
        self.stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.piece_img = page.locator("img.rc-slider-captcha-jigsaw-puzzle")
        self.piece_bg = page.locator("img.rc-slider-captcha-jigsaw-bg")

    def wait_for_human_interaction(self, timeout: int = 5000):
        print("Waiting for human interaction...")
        self.page.wait_for_timeout(timeout)

    def save_puzzle_piece(self) -> str:
        # Ensure the element exists before reading its attribute
        try:
            self.piece_img.wait_for(state="attached", timeout=5000)
        except PlaywrightTimeoutError:
            raise RuntimeError("Puzzle piece image not found on the page.")

        src = self.piece_img.get_attribute("src")
        if not src:
            raise RuntimeError("Image 'src' attribute is missing.")
        if "base64," not in src:
            # Fallback: if it's a normal URL, tell the caller to fetch it differently
            raise RuntimeError("Image src is not a base64 data URI.")

        # Extract the base64 payload
        b64_data = src.split("base64,", 1)[1]
        if not b64_data:
            raise RuntimeError("Empty base64 payload in image src.")

        # Decode and save
        try:
            image_bytes = base64.b64decode(b64_data, validate=True)
        except Exception as e:
            raise RuntimeError(f"Failed to decode base64 image: {e}")

        out_dir = Path("data_puzzle")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{self.stamp}_image_puzzle_piece.png"
        out_path.write_bytes(image_bytes)
        print(f"Image saved to {out_path}")
        return str(out_path)

    def save_puzzle_bg(self) -> str:
        # Ensure the element exists before reading its attribute
        try:
            self.piece_bg.wait_for(state="attached", timeout=5000)
        except PlaywrightTimeoutError:
            raise RuntimeError("Puzzle background image not found on the page.")

        src = self.piece_bg.get_attribute("src")
        if not src:
            raise RuntimeError("Image 'src' attribute is missing.")
        if "base64," not in src:
            # Fallback: if it's a normal URL, tell the caller to fetch it differently
            raise RuntimeError("Image src is not a base64 data URI.")

        # Extract the base64 payload
        b64_data = src.split("base64,", 1)[1]
        if not b64_data:
            raise RuntimeError("Empty base64 payload in image src.")

        # Decode and save
        try:
            image_bytes = base64.b64decode(b64_data, validate=True)
        except Exception as e:
            raise RuntimeError(f"Failed to decode base64 image: {e}")

        out_dir = Path("data_puzzle")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{self.stamp}_image_puzzle_bg.png"
        out_path.write_bytes(image_bytes)
        print(f"Image saved to {out_path}")
        return str(out_path)
