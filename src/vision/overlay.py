from pathlib import Path

import cv2


def render_puzzle_overlay(
    bg_path: str, match_xy: tuple[int, int], tpl_wh: tuple[int, int], out_path: Path
) -> None:
    bg = cv2.imread(bg_path, cv2.IMREAD_COLOR)
    x, y = match_xy
    tw, th = tpl_wh
    tl = (int(x), int(y))
    br = (int(x + tw), int(y + th))
    overlay = bg.copy()
    cv2.rectangle(overlay, tl, br, (0, 0, 255), 2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), overlay)
