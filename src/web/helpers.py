import base64
from datetime import datetime
from pathlib import Path
from time import monotonic

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.logging_utils import log_print


class Helpers:
    _PUZZLE_IMAGE_ATTACH_TIMEOUT_MS: int = 5000
    _PUZZLE_REFRESH_POLL_MS: int = 150

    def __init__(self, page: Page) -> None:
        self.page = page
        self.folder_stamp = datetime.now().strftime("%Y-%m-%d")
        self.stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.piece_img = page.locator("img.rc-slider-captcha-jigsaw-puzzle")
        self.piece_bg = page.locator("img.rc-slider-captcha-jigsaw-bg")

    def save_puzzle_piece(self, nik: str) -> str:
        return self._save_data_uri_image(
            locator=self.piece_img,
            output_name=self.build_puzzle_output_name(nik, "piece"),
            missing_message="Puzzle piece image not found on the page.",
        )

    def save_puzzle_bg(self, nik: str) -> str:
        return self._save_data_uri_image(
            locator=self.piece_bg,
            output_name=self.build_puzzle_output_name(nik, "bg"),
            missing_message="Puzzle background image not found on the page.",
        )

    def build_puzzle_output_name(self, nik: str, image_type: str) -> str:
        nik_prefix = f"{str(nik).strip()}_" if str(nik).strip() else ""
        return f"{nik_prefix}{self.stamp}_image_puzzle_{image_type}.png"

    def get_puzzle_image_sources(self) -> tuple[str, str]:
        """Return the current background and piece image sources."""
        bg_src = self._get_image_src(
            locator=self.piece_bg,
            missing_message="Puzzle background image not found on the page.",
        )
        piece_src = self._get_image_src(
            locator=self.piece_img,
            missing_message="Puzzle piece image not found on the page.",
        )
        return bg_src, piece_src

    def wait_for_puzzle_refresh(
        self,
        *,
        previous_bg_src: str,
        previous_piece_src: str,
        timeout_ms: int,
    ) -> bool:
        """Wait until the puzzle challenge rotates to a new image pair."""
        deadline = monotonic() + (timeout_ms / 1000.0)

        while monotonic() < deadline:
            try:
                current_bg_src, current_piece_src = self.get_puzzle_image_sources()
            except RuntimeError:
                self.page.wait_for_timeout(self._PUZZLE_REFRESH_POLL_MS)
                continue

            if (
                current_bg_src != previous_bg_src
                or current_piece_src != previous_piece_src
            ):
                log_print("Detected refreshed puzzle images for retry.")
                return True

            self.page.wait_for_timeout(self._PUZZLE_REFRESH_POLL_MS)

        log_print("Puzzle images did not refresh before retry timeout; reusing current challenge state.")
        return False

    def _save_data_uri_image(
        self, *, locator: Locator, output_name: str, missing_message: str
    ) -> str:
        src = self._get_image_src(locator=locator, missing_message=missing_message)
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

    def _get_image_src(self, *, locator: Locator, missing_message: str) -> str:
        self._wait_for_image(locator=locator, missing_message=missing_message)
        src = locator.get_attribute("src")
        if not src:
            raise RuntimeError("Image 'src' attribute is missing.")
        return src

    def _wait_for_image(self, *, locator: Locator, missing_message: str) -> None:
        try:
            locator.wait_for(
                state="attached", timeout=self._PUZZLE_IMAGE_ATTACH_TIMEOUT_MS
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(missing_message) from exc

    @staticmethod
    def _extract_base64_payload(src: str) -> str:
        if "base64," not in src:
            raise RuntimeError("Image src is not a base64 data URI.")

        payload = src.split("base64,", 1)[1]
        if not payload:
            raise RuntimeError("Empty base64 payload in image src.")

        return payload
