from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


class MaskProcessor:
    """Processes alpha masks to extract puzzle tile information."""

    def __init__(self, alpha_threshold: int = 5) -> None:
        self.alpha_threshold = alpha_threshold

    def compute_slot_left_x(
        self, piece_img_path: Path, x_piece: float, tpl_w: int
    ) -> tuple[float, int]:
        """
        Recover puzzle slot left X coordinate in background pixels.

        Returns: (slot_left_x_in_bg, puzzle_tile_width_in_image_px)
        """
        piece_img = cv2.imread(str(piece_img_path), cv2.IMREAD_UNCHANGED)
        if piece_img is None:
            return float(x_piece), tpl_w

        _h, w = piece_img.shape[:2]
        has_alpha = piece_img.ndim == 3 and piece_img.shape[2] == 4
        if not has_alpha:
            return float(x_piece), w

        mask = self._extract_alpha_mask(piece_img)

        _ys, xs = np.where(mask > 0)
        if xs.size == 0:
            return float(x_piece), w

        alpha_x0 = int(xs.min())
        alpha_x1 = int(xs.max())
        cropped_width = alpha_x1 - alpha_x0 + 1

        scale_crop_to_tpl = tpl_w / float(cropped_width)
        slot_left_x = float(x_piece) - alpha_x0 * scale_crop_to_tpl

        return slot_left_x, w

    def _extract_alpha_mask(self, img: np.ndarray) -> np.ndarray:
        """Extract and process alpha channel mask."""
        alpha = img[:, :, 3]
        mask = (alpha > self.alpha_threshold).astype(np.uint8) * 255

        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1
        )
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1
        )
        return mask
