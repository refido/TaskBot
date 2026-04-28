from __future__ import annotations

import cv2

from src.vision.puzzle.types import GrayImage, PointF


def draw_match_visualization(
    bg_gray: GrayImage,
    tl: PointF,
    tw: int,
    th: int,
    score: float,
    tpl_center_local: PointF | None = None,
) -> GrayImage:
    """
    Visualization with confidence color and true jigsaw center.

    tl: (x, y) top-left of template in background (float).
    tpl_center_local: (cx, cy) center in template-local coordinates (float).
    """
    vis = cv2.cvtColor(bg_gray, cv2.COLOR_GRAY2BGR)

    tl_int = (int(round(tl[0])), int(round(tl[1])))
    br = (int(round(tl[0] + tw)), int(round(tl[1] + th)))

    if score > 0.85:
        color = (0, 255, 0)
    elif score > 0.75:
        color = (0, 255, 255)
    else:
        color = (0, 165, 255)

    cv2.rectangle(vis, tl_int, br, color, 2)

    if tpl_center_local is not None:
        center_x = tl[0] + tpl_center_local[0]
        center_y = tl[1] + tpl_center_local[1]
    else:
        center_x = tl[0] + tw / 2.0
        center_y = tl[1] + th / 2.0

    center_int = (int(round(center_x)), int(round(center_y)))

    cv2.circle(vis, center_int, radius=8, color=color, thickness=-1)
    cv2.circle(vis, center_int, radius=8, color=(255, 255, 255), thickness=2)

    crosshair_size = 15
    cv2.line(
        vis,
        (center_int[0] - crosshair_size, center_int[1]),
        (center_int[0] + crosshair_size, center_int[1]),
        (255, 255, 255),
        2,
    )
    cv2.line(
        vis,
        (center_int[0], center_int[1] - crosshair_size),
        (center_int[0], center_int[1] + crosshair_size),
        (255, 255, 255),
        2,
    )

    score_text = f"Score: {score:.4f}"
    cv2.putText(
        vis,
        score_text,
        (tl_int[0], tl_int[1] - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )

    coords_text = f"Pos: ({int(round(center_x))}, {int(round(center_y))})"
    cv2.putText(
        vis,
        coords_text,
        (tl_int[0], br[1] + 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 0),
        1,
    )

    return vis
