import base64
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.logging_utils import log_print


class Helpers:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.folder_stamp = datetime.now().strftime("%Y-%m-%d")
        self.stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.piece_img = page.locator("img.rc-slider-captcha-jigsaw-puzzle")
        self.piece_bg = page.locator("img.rc-slider-captcha-jigsaw-bg")

    def save_puzzle_piece(self) -> str:
        return self._save_data_uri_image(
            locator=self.piece_img,
            output_name=f"{self.stamp}_image_puzzle_piece.png",
            missing_message="Puzzle piece image not found on the page.",
        )

    def save_puzzle_bg(self) -> str:
        return self._save_data_uri_image(
            locator=self.piece_bg,
            output_name=f"{self.stamp}_image_puzzle_bg.png",
            missing_message="Puzzle background image not found on the page.",
        )

    def _save_data_uri_image(
        self, *, locator: Locator, output_name: str, missing_message: str
    ) -> str:
        try:
            locator.wait_for(state="attached", timeout=5000)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(missing_message) from exc

        src = locator.get_attribute("src")
        if not src:
            raise RuntimeError("Image 'src' attribute is missing.")

        payload = self._extract_base64_payload(src)

        try:
            image_bytes = base64.b64decode(payload, validate=True)
        except Exception as exc:
            raise RuntimeError(f"Failed to decode base64 image: {exc}") from exc

        out_dir = Path(f"data_puzzle/{self.folder_stamp}")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / output_name
        out_path.write_bytes(image_bytes)
        log_print(f"Image saved to {out_path}")
        return str(out_path)

    @staticmethod
    def _extract_base64_payload(src: str) -> str:
        if "base64," not in src:
            raise RuntimeError("Image src is not a base64 data URI.")

        payload = src.split("base64,", 1)[1]
        if not payload:
            raise RuntimeError("Empty base64 payload in image src.")

        return payload
