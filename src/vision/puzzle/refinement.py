from __future__ import annotations

import cv2
import numpy as np

from src.vision.puzzle.preprocessing import build_match_mask
from src.vision.puzzle.types import FloatMap, GrayImage, MaskImage, Point, PointF


def local_ncc_refine(
    bg_gray: GrayImage,
    tpl_gray: GrayImage,
    xy: Point,
    radius: int = 3,
    mask: MaskImage | None = None,
) -> tuple[Point, float]:
    """
    Final refinement in a small window using raw correlation.

    Returns:
        (best_xy, best_score) where best_xy is (x, y).
        If no valid candidate is found, returns (xy, -1.0).
    """
    x0, y0 = int(xy[0]), int(xy[1])
    th, tw = tpl_gray.shape[:2]
    h_bg, w_bg = bg_gray.shape[:2]
    match_mask = build_match_mask(mask, erode_iterations=0)

    best_xy = (x0, y0)
    best_score = -1.0

    for dy in range(-radius, radius + 1):
        y = y0 + dy
        if y < 0 or y + th > h_bg:
            continue

        for dx in range(-radius, radius + 1):
            x = x0 + dx
            if x < 0 or x + tw > w_bg:
                continue

            roi = bg_gray[y : y + th, x : x + tw]
            if match_mask is not None:
                try:
                    res = cv2.matchTemplate(
                        roi, tpl_gray, cv2.TM_CCORR_NORMED, mask=match_mask
                    )
                except cv2.error:
                    res = cv2.matchTemplate(roi, tpl_gray, cv2.TM_CCOEFF_NORMED)
            else:
                res = cv2.matchTemplate(roi, tpl_gray, cv2.TM_CCOEFF_NORMED)

            score = float(res[0, 0])
            if score > best_score:
                best_score = score
                best_xy = (x, y)

    if best_score < 0:
        return (x0, y0), -1.0

    return best_xy, best_score


def subpixel_refine(res_map: FloatMap, max_loc: Point, win: int = 2) -> PointF:
    """
    Sub-pixel refinement using local 2D quadratic fit around the peak.
    Returns (x_sub, y_sub) in the same coordinates as max_loc.
    """
    x, y = max_loc
    h, w = res_map.shape

    x0 = max(0, x - win)
    x1 = min(w, x + win + 1)
    y0 = max(0, y - win)
    y1 = min(h, y + win + 1)

    patch = res_map[y0:y1, x0:x1].astype(np.float32)

    ys, xs = np.mgrid[y0:y1, x0:x1].reshape(2, -1)
    xs = xs.astype(np.float32) - float(x)
    ys = ys.astype(np.float32) - float(y)
    z = patch.reshape(-1)

    a_mat = np.vstack([xs * xs, ys * ys, xs * ys, xs, ys, np.ones_like(xs)]).T
    try:
        coeff, _, _, _ = np.linalg.lstsq(a_mat, z, rcond=None)
    except np.linalg.LinAlgError:
        return float(x), float(y)

    a, b, c, d, e, _f = coeff

    denom = 4 * a * b - c * c
    if abs(denom) < 1e-6:
        return float(x), float(y)

    dx = (c * e - 2 * b * d) / denom
    dy = (c * d - 2 * a * e) / denom

    dx = float(np.clip(dx, -0.5, 0.5))
    dy = float(np.clip(dy, -0.5, 0.5))

    return float(x + dx), float(y + dy)


def chamfer_refine(
    bg_gray: GrayImage,
    tpl_gray: GrayImage,
    coarse_xy: Point,
    search_radius: int = 5,
    mask: MaskImage | None = None,
) -> tuple[Point, float]:
    """Chamfer refinement with a local translation search."""
    th, tw = tpl_gray.shape[:2]
    x0 = max(0, coarse_xy[0] - search_radius)
    y0 = max(0, coarse_xy[1] - search_radius)
    x1 = min(bg_gray.shape[1], coarse_xy[0] + tw + search_radius)
    y1 = min(bg_gray.shape[0], coarse_xy[1] + th + search_radius)
    roi = bg_gray[y0:y1, x0:x1]

    if roi.shape[0] < th or roi.shape[1] < tw:
        return coarse_xy, float("inf")

    roi_median = np.median(roi)
    sigma = 0.33
    lower_canny = int(max(15, (1.0 - sigma) * roi_median))
    upper_canny = int(min(150, (1.0 + sigma) * roi_median))

    roi_edges = cv2.Canny(roi, lower_canny, upper_canny, L2gradient=True)
    inv = (roi_edges == 0).astype(np.uint8) * 255
    dt = cv2.distanceTransform(inv, cv2.DIST_L2, 5).astype(np.float32)

    tpl_median = np.median(tpl_gray)
    lower_tpl = int(max(15, (1.0 - sigma) * tpl_median))
    upper_tpl = int(min(150, (1.0 + sigma) * tpl_median))

    tpl_edges = cv2.Canny(tpl_gray, lower_tpl, upper_tpl, L2gradient=True)
    if mask is not None:
        match_mask = build_match_mask(mask, erode_iterations=0)
        if match_mask is not None:
            tpl_edges = cv2.bitwise_and(tpl_edges, match_mask)
    tpl_edges = (tpl_edges > 0).astype(np.float32)

    res = cv2.matchTemplate(dt, tpl_edges, cv2.TM_SQDIFF)
    min_val, _, min_loc, _ = cv2.minMaxLoc(res)

    refined = (x0 + min_loc[0], y0 + min_loc[1])

    dx = abs(refined[0] - coarse_xy[0])
    dy = abs(refined[1] - coarse_xy[1])

    if dx <= 4 and dy <= 4:
        return refined, float(min_val)
    return coarse_xy, float(min_val)


def ecc_refine(
    bg_gray: GrayImage,
    tpl_gray: GrayImage,
    coarse_xy: Point,
    mask: MaskImage | None = None,
    max_shift: float = 3.0,
) -> tuple[PointF, float]:
    """
    Refine a coarse translation estimate with ECC alignment.

    ECC uses a same-size patch centered on the current estimate, which makes it
    stable for small residual errors after coarse candidate scoring.
    """
    th, tw = tpl_gray.shape[:2]
    x, y = int(coarse_xy[0]), int(coarse_xy[1])

    if (
        x < 0
        or y < 0
        or x + tw > bg_gray.shape[1]
        or y + th > bg_gray.shape[0]
    ):
        return (float(x), float(y)), -1.0

    patch = bg_gray[y : y + th, x : x + tw].astype(np.float32) / 255.0
    template = tpl_gray.astype(np.float32) / 255.0
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        40,
        1e-5,
    )
    match_mask = build_match_mask(mask, erode_iterations=0)

    try:
        ecc_score, warp = cv2.findTransformECC(
            template,
            patch,
            warp,
            cv2.MOTION_TRANSLATION,
            criteria,
            inputMask=match_mask,
            gaussFiltSize=3,
        )
    except cv2.error:
        return (float(x), float(y)), -1.0

    dx = float(np.clip(warp[0, 2], -max_shift, max_shift))
    dy = float(np.clip(warp[1, 2], -max_shift, max_shift))
    return (float(x + dx), float(y + dy)), float(ecc_score)
