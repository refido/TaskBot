from pathlib import Path

import cv2
import numpy as np


def render_puzzle_overlay(
    bg_path: str,
    match_xy: tuple[int, int],
    tpl_wh: tuple[int, int],
    out_path: Path,
    bg_img: np.ndarray | None = None,
) -> None:
    bg = bg_img
    if bg is None:
        bg = cv2.imread(bg_path, cv2.IMREAD_COLOR)
    if bg is None:
        return
    if bg.ndim == 2:
        bg = cv2.cvtColor(bg, cv2.COLOR_GRAY2BGR)
    elif bg.shape[2] == 4:
        bg = cv2.cvtColor(bg, cv2.COLOR_BGRA2BGR)
    x, y = match_xy
    tw, th = tpl_wh
    tl = (int(x), int(y))
    br = (int(x + tw), int(y + th))
    overlay = bg.copy()
    cv2.rectangle(overlay, tl, br, (0, 0, 255), 2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), overlay)
