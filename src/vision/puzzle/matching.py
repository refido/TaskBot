from __future__ import annotations

import cv2
import numpy as np

from src.vision.puzzle.types import Candidate, FloatMap, GrayImage, MaskImage, Point, YRoi


def compute_structural_complexity(
    gray: GrayImage, loc: Point, template_shape: tuple[int, int]
) -> float:
    """
    Measure structural complexity at a given location.
    Returns higher values for regions with more features.
    """
    th, tw = template_shape
    x, y = int(loc[0]), int(loc[1])

    y0 = max(0, y)
    y1 = min(gray.shape[0], y + th)
    x0 = max(0, x)
    x1 = min(gray.shape[1], x + tw)

    if y1 - y0 < th // 2 or x1 - x0 < tw // 2:
        return 0.0

    region = gray[y0:y1, x0:x1]

    edges = cv2.Canny(region, 30, 100, L2gradient=True)
    edge_density = np.sum(edges > 0) / (region.shape[0] * region.shape[1])

    texture_var = np.std(region)

    gx = cv2.Sobel(region, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(region, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = np.mean(cv2.magnitude(gx, gy))

    hist = cv2.calcHist([region], [0], None, [256], [0, 256])
    hist = hist / (hist.sum() + 1e-7)
    entropy = -np.sum(hist * np.log2(hist + 1e-7))

    complexity = (
        edge_density * 0.3
        + (texture_var / 128.0) * 0.25
        + (grad_mag / 255.0) * 0.25
        + (entropy / 8.0) * 0.2
    )
    return float(complexity)


def filter_candidates_by_complexity(
    res_map: FloatMap,
    bg_gray: GrayImage,
    tpl_shape: tuple[int, int],
    top_k: int = 10,
    use_complexity: bool = True,
) -> list[Candidate]:
    """
    Get top-k candidates and validate with complexity thresholds.

    When use_complexity=False (low-texture templates like sky),
    ranking is based almost purely on match score and complexity
    only provides a tiny bonus. This avoids penalizing valid
    matches in smooth regions.
    """
    res_flat = res_map.flatten()
    top_indices = np.argpartition(res_flat, -top_k)[-top_k:]
    top_indices = top_indices[np.argsort(-res_flat[top_indices])]

    _h, w = res_map.shape
    candidates: list[Candidate] = []

    for idx in top_indices:
        y = int(idx // w)
        x = int(idx % w)
        score = float(res_map[y, x])

        complexity = compute_structural_complexity(bg_gray, (x, y), tpl_shape)

        if use_complexity:
            if complexity < 0.15:
                complexity_penalty = -0.15
            elif complexity < 0.25:
                complexity_penalty = -0.05
            else:
                complexity_penalty = min(0.10, complexity * 0.2)
            combined_score = score + complexity_penalty
        else:
            complexity_bonus = min(0.05, max(0.0, complexity) * 0.1)
            combined_score = score + complexity_bonus

        candidates.append(
            Candidate(
                loc=(x, y),
                match_score=score,
                complexity=float(complexity),
                combined_score=float(combined_score),
            )
        )

    candidates.sort(key=lambda c: c.combined_score, reverse=True)
    return candidates


def is_uniform_region(
    gray: GrayImage,
    loc: Point,
    template_shape: tuple[int, int],
    threshold: float = 0.02,
    uniform_std_threshold: float = 15.0,
) -> bool:
    """
    Detect uniform/low-detail regions (grass, solid colors).
    Returns True if region is too uniform to be a valid match.
    """
    th, tw = template_shape
    x, y = int(loc[0]), int(loc[1])

    y0 = max(0, y)
    y1 = min(gray.shape[0], y + th)
    x0 = max(0, x)
    x1 = min(gray.shape[1], x + tw)

    if y1 - y0 < th // 2 or x1 - x0 < tw // 2:
        return True

    region = gray[y0:y1, x0:x1]

    edges = cv2.Canny(region, 30, 100, L2gradient=True)
    edge_density = np.sum(edges > 0) / (region.shape[0] * region.shape[1])

    std_dev = np.std(region)
    return bool((edge_density < threshold) and (std_dev < uniform_std_threshold))


def match_maps_fused(
    bg_gray: GrayImage, tpl_gray: GrayImage, tpl_mask: MaskImage | None
) -> FloatMap:
    """Enhanced matching with uniform region filtering."""
    m = None
    if tpl_mask is not None:
        m = tpl_mask
        if m.dtype != np.uint8:
            m = m.astype(np.uint8)
        if m.max() <= 1:
            m = (m > 0).astype(np.uint8) * 255

    res_corr = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCORR_NORMED, mask=m)
    res_coef = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
    res_sqdiff = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_SQDIFF_NORMED)
    res_sqdiff = 1.0 - res_sqdiff

    res_corr = cv2.normalize(res_corr, None, 0, 1, cv2.NORM_MINMAX)
    res_coef = cv2.normalize(res_coef, None, 0, 1, cv2.NORM_MINMAX)
    res_sqdiff = cv2.normalize(res_sqdiff, None, 0, 1, cv2.NORM_MINMAX)

    max_corr = res_corr.max()
    max_coef = res_coef.max()
    max_sqdiff = res_sqdiff.max()

    total = max_corr + max_coef + max_sqdiff + 1e-7
    w_corr = max(0.3, max_corr / total)
    w_coef = max(0.3, max_coef / total)
    w_sqdiff = max(0.2, max_sqdiff / total)

    total_w = w_corr + w_coef + w_sqdiff
    w_corr /= total_w
    w_coef /= total_w
    w_sqdiff /= total_w

    fused = w_corr * res_corr + w_coef * res_coef + w_sqdiff * res_sqdiff

    tpl_shape = tpl_gray.shape[:2]
    candidates = filter_candidates_by_complexity(fused, bg_gray, tpl_shape, top_k=10)
    valid_candidates = [
        c for c in candidates if not is_uniform_region(bg_gray, c.loc, tpl_shape)
    ]

    if not valid_candidates:
        valid_candidates = candidates[:1]

    # Keep behavior: when all maps are ambiguous, still force one valid region.
    # The returned map is unchanged; this pass only preserves filtering parity.
    return fused


def compute_fused_and_chamfer_maps(
    *,
    bg_grad: GrayImage,
    tpl_grad: GrayImage,
    edge_mask: MaskImage,
    dt_full: FloatMap,
    tpl_edges_f: FloatMap,
    bg_gray: GrayImage,
    y_roi: YRoi,
) -> tuple[FloatMap, FloatMap, GrayImage]:
    if y_roi is not None:
        y0, y1 = y_roi
        fused_map = match_maps_fused(bg_grad[y0:y1, :], tpl_grad, edge_mask)
        dt_roi = dt_full[y0:y1, :]
        res_dt = cv2.matchTemplate(dt_roi, tpl_edges_f, cv2.TM_SQDIFF)
        res_dt = cv2.normalize(res_dt, None, 0, 1, cv2.NORM_MINMAX)
        chamfer_sim = 1.0 - res_dt
        bg_gray_for_rank = bg_gray[y0:y1, :]
    else:
        fused_map = match_maps_fused(bg_grad, tpl_grad, edge_mask)
        res_dt = cv2.matchTemplate(dt_full, tpl_edges_f, cv2.TM_SQDIFF)
        res_dt = cv2.normalize(res_dt, None, 0, 1, cv2.NORM_MINMAX)
        chamfer_sim = 1.0 - res_dt
        bg_gray_for_rank = bg_gray

    return fused_map, chamfer_sim, bg_gray_for_rank
