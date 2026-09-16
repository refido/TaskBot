from __future__ import annotations

import cv2
import numpy as np

from src.vision.puzzle.preprocessing import build_match_mask
from src.vision.puzzle.types import (
    Candidate,
    FloatMap,
    GrayImage,
    MaskImage,
    OrbMatch,
    Point,
    YRoi,
)


def _normalize_map(res_map: FloatMap) -> FloatMap:
    res_map = res_map.astype(np.float32)
    if res_map.size == 0:
        return res_map

    min_val = float(np.min(res_map))
    max_val = float(np.max(res_map))
    if max_val - min_val < 1e-6:
        return np.zeros_like(res_map, dtype=np.float32)

    return cv2.normalize(res_map, None, 0.0, 1.0, cv2.NORM_MINMAX).astype(np.float32)


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
    if res_map.size == 0:
        return []

    res_flat = res_map.ravel()
    top_k = min(max(1, int(top_k)), int(res_flat.size))
    if top_k == res_flat.size:
        top_indices = np.argsort(-res_flat)
    else:
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


def compute_template_similarity_map(
    bg_gray: GrayImage, tpl_gray: GrayImage, tpl_mask: MaskImage | None
) -> FloatMap:
    mask = build_match_mask(tpl_mask, erode_iterations=1)

    if mask is not None:
        try:
            res_corr = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCORR_NORMED, mask=mask)
            res_sqdiff = cv2.matchTemplate(
                bg_gray, tpl_gray, cv2.TM_SQDIFF_NORMED, mask=mask
            )
        except cv2.error:
            mask = None

    if mask is None:
        res_corr = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCORR_NORMED)
        res_sqdiff = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_SQDIFF_NORMED)

    res_coef = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
    res_sqdiff = 1.0 - res_sqdiff

    res_corr = _normalize_map(res_corr)
    res_coef = _normalize_map(res_coef)
    res_sqdiff = _normalize_map(res_sqdiff)

    template_std = float(np.std(tpl_gray))
    if mask is not None:
        w_corr, w_coef, w_sqdiff = 0.42, 0.18, 0.40
    else:
        w_corr, w_coef, w_sqdiff = 0.34, 0.33, 0.33

    if template_std < 18.0:
        w_corr += 0.08
        w_sqdiff += 0.07
        w_coef = max(0.10, w_coef - 0.15)

    total_w = w_corr + w_coef + w_sqdiff
    w_corr /= total_w
    w_coef /= total_w
    w_sqdiff /= total_w

    return (
        w_corr * res_corr + w_coef * res_coef + w_sqdiff * res_sqdiff
    ).astype(np.float32)


def match_maps_fused(
    bg_gray: GrayImage, tpl_gray: GrayImage, tpl_mask: MaskImage | None
) -> FloatMap:
    """Build the fused template score map without redundant candidate scans."""
    return compute_template_similarity_map(bg_gray, tpl_gray, tpl_mask)


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
        res_dt = _normalize_map(res_dt)
        chamfer_sim = 1.0 - res_dt
        bg_gray_for_rank = bg_gray[y0:y1, :]
    else:
        fused_map = match_maps_fused(bg_grad, tpl_grad, edge_mask)
        res_dt = cv2.matchTemplate(dt_full, tpl_edges_f, cv2.TM_SQDIFF)
        res_dt = _normalize_map(res_dt)
        chamfer_sim = 1.0 - res_dt
        bg_gray_for_rank = bg_gray

    return fused_map, chamfer_sim.astype(np.float32), bg_gray_for_rank


def _candidate_box(loc: Point, template_shape: tuple[int, int]) -> tuple[int, int, int, int]:
    th, tw = template_shape
    return int(loc[0]), int(loc[1]), int(tw), int(th)


def compute_box_iou(
    box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]
) -> float:
    ax0, ay0, aw, ah = box_a
    bx0, by0, bw, bh = box_b

    ax1 = ax0 + aw
    ay1 = ay0 + ah
    bx1 = bx0 + bw
    by1 = by0 + bh

    inter_x0 = max(ax0, bx0)
    inter_y0 = max(ay0, by0)
    inter_x1 = min(ax1, bx1)
    inter_y1 = min(ay1, by1)

    inter_w = max(0, inter_x1 - inter_x0)
    inter_h = max(0, inter_y1 - inter_y0)
    inter_area = inter_w * inter_h

    union_area = aw * ah + bw * bh - inter_area
    if union_area <= 0:
        return 0.0
    return float(inter_area / union_area)


def extract_top_peak_candidates(
    res_map: FloatMap, top_k: int = 6, suppression_radius: int = 10
) -> list[Candidate]:
    working = _normalize_map(res_map).copy()
    candidates: list[Candidate] = []

    for _ in range(max(1, top_k)):
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(working)
        if max_val <= 0:
            break

        x = int(max_loc[0])
        y = int(max_loc[1])
        candidates.append(
            Candidate(loc=(x, y), match_score=float(max_val), combined_score=float(max_val))
        )

        x0 = max(0, x - suppression_radius)
        x1 = min(working.shape[1], x + suppression_radius + 1)
        y0 = max(0, y - suppression_radius)
        y1 = min(working.shape[0], y + suppression_radius + 1)
        working[y0:y1, x0:x1] = 0.0

    return candidates


def non_max_suppress_candidates(
    candidates: list[Candidate],
    template_shape: tuple[int, int],
    iou_threshold: float = 0.35,
    limit: int | None = None,
) -> list[Candidate]:
    ordered = sorted(
        candidates,
        key=lambda c: float(
            c.final_score
            if c.final_score is not None
            else c.combined_score if c.combined_score else c.match_score
        ),
        reverse=True,
    )

    selected: list[Candidate] = []
    for candidate in ordered:
        cand_box = _candidate_box(candidate.loc, template_shape)
        if any(
            compute_box_iou(cand_box, _candidate_box(existing.loc, template_shape))
            >= iou_threshold
            for existing in selected
        ):
            continue
        selected.append(candidate)
        if limit is not None and len(selected) >= limit:
            break

    return selected


def _local_peak_score(res_map: FloatMap, loc: Point, radius: int = 1) -> float:
    x, y = int(loc[0]), int(loc[1])
    y0 = max(0, y - radius)
    y1 = min(res_map.shape[0], y + radius + 1)
    x0 = max(0, x - radius)
    x1 = min(res_map.shape[1], x + radius + 1)
    patch = res_map[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    return float(np.max(patch))


def compute_edge_iou(
    bg_edges: MaskImage,
    tpl_edges: MaskImage,
    loc: Point,
    tpl_mask: MaskImage | None = None,
) -> float:
    th, tw = tpl_edges.shape[:2]
    x, y = int(loc[0]), int(loc[1])

    if (
        x < 0
        or y < 0
        or x + tw > bg_edges.shape[1]
        or y + th > bg_edges.shape[0]
    ):
        return 0.0

    roi = bg_edges[y : y + th, x : x + tw]
    kernel = np.ones((3, 3), np.uint8)
    roi_eval = cv2.dilate(roi, kernel, iterations=1) > 0
    tpl_eval = cv2.dilate(tpl_edges, kernel, iterations=1) > 0

    if tpl_mask is not None:
        valid = build_match_mask(tpl_mask, erode_iterations=0)
        valid_mask = valid > 0 if valid is not None else np.ones_like(tpl_eval, dtype=bool)
    else:
        valid_mask = np.ones_like(tpl_eval, dtype=bool)

    intersection = np.logical_and(roi_eval, tpl_eval)
    intersection = np.logical_and(intersection, valid_mask).sum()

    union = np.logical_or(roi_eval, tpl_eval)
    union = np.logical_and(union, valid_mask).sum()
    if union <= 0:
        return 0.0
    return float(intersection / union)


def compute_orb_match(
    bg_gray: GrayImage, tpl_gray: GrayImage, tpl_mask: MaskImage | None = None
) -> OrbMatch | None:
    mask = build_match_mask(tpl_mask, erode_iterations=0)
    orb = cv2.ORB_create(
        nfeatures=768,
        scaleFactor=1.2,
        nlevels=8,
        edgeThreshold=7,
        patchSize=31,
        fastThreshold=10,
    )

    kp_tpl, des_tpl = orb.detectAndCompute(tpl_gray, mask)
    kp_bg, des_bg = orb.detectAndCompute(bg_gray, None)

    if des_tpl is None or des_bg is None or len(kp_tpl) < 4 or len(kp_bg) < 8:
        return None

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(des_tpl, des_bg, k=2)
    good_matches = []
    for pair in pairs:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.78 * n.distance:
            good_matches.append(m)

    if len(good_matches) < 4:
        return None

    src_pts = np.float32([kp_tpl[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_bg[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

    homography, inlier_mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 4.0)
    if homography is not None and inlier_mask is not None:
        inliers = int(inlier_mask.ravel().sum())
        if inliers >= 4:
            th, tw = tpl_gray.shape[:2]
            corners = np.float32([[0, 0], [tw, 0], [tw, th], [0, th]]).reshape(-1, 1, 2)
            projected = cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
            x, y, w, h = cv2.boundingRect(projected.astype(np.float32))

            area_ratio = (w * h) / float(max(1, tw * th))
            if w > 0 and h > 0 and 0.45 <= area_ratio <= 2.5:
                x = int(np.clip(x, 0, max(0, bg_gray.shape[1] - w)))
                y = int(np.clip(y, 0, max(0, bg_gray.shape[0] - h)))
                score = 0.55 * min(1.0, inliers / 12.0) + 0.45 * (
                    inliers / max(len(good_matches), 1)
                )
                return OrbMatch(
                    loc=(x, y),
                    bbox=(x, y, int(w), int(h)),
                    inliers=inliers,
                    matches=len(good_matches),
                    score=float(np.clip(score, 0.0, 1.0)),
                )

    offsets = dst_pts[:, 0, :] - src_pts[:, 0, :]
    median_offset = np.median(offsets, axis=0)
    inliers = np.linalg.norm(offsets - median_offset, axis=1) <= 6.0
    inlier_count = int(np.sum(inliers))
    if inlier_count < 3:
        return None

    x = int(round(float(median_offset[0])))
    y = int(round(float(median_offset[1])))
    th, tw = tpl_gray.shape[:2]
    x = int(np.clip(x, 0, max(0, bg_gray.shape[1] - tw)))
    y = int(np.clip(y, 0, max(0, bg_gray.shape[0] - th)))
    score = 0.5 * min(1.0, inlier_count / 10.0) + 0.5 * (
        inlier_count / max(len(good_matches), 1)
    )
    return OrbMatch(
        loc=(x, y),
        bbox=(x, y, int(tw), int(th)),
        inliers=inlier_count,
        matches=len(good_matches),
        score=float(np.clip(score, 0.0, 1.0)),
    )


def rescore_candidate(
    *,
    bg_gray: GrayImage,
    tpl_gray: GrayImage,
    tpl_mask: MaskImage | None,
    template_map: FloatMap,
    gradient_map: FloatMap,
    chamfer_map: FloatMap,
    bg_edges: MaskImage,
    tpl_edges: MaskImage,
    bg_gray_for_rank: GrayImage,
    initial_loc: Point,
    orb_match: OrbMatch | None,
    distinctiveness: float,
    search_radius: int = 4,
) -> Candidate:
    th, tw = tpl_gray.shape[:2]
    x, y = int(initial_loc[0]), int(initial_loc[1])

    x0 = max(0, x - search_radius)
    y0 = max(0, y - search_radius)
    x1 = min(bg_gray.shape[1], x + tw + search_radius)
    y1 = min(bg_gray.shape[0], y + th + search_radius)

    if y1 - y0 < th or x1 - x0 < tw:
        return Candidate(loc=(x, y), match_score=0.0, combined_score=0.0)

    roi_gray = bg_gray[y0:y1, x0:x1]
    local_map = compute_template_similarity_map(roi_gray, tpl_gray, tpl_mask)
    _min_val, _max_val, _min_loc, local_best_loc = cv2.minMaxLoc(local_map)
    refined_loc = (int(x0 + local_best_loc[0]), int(y0 + local_best_loc[1]))

    template_score = _local_peak_score(template_map, refined_loc, radius=1)
    gradient_score = _local_peak_score(gradient_map, refined_loc, radius=1)
    chamfer_score = _local_peak_score(chamfer_map, refined_loc, radius=1)
    edge_iou = compute_edge_iou(bg_edges, tpl_edges, refined_loc, tpl_mask)

    complexity = compute_structural_complexity(bg_gray_for_rank, refined_loc, (th, tw))
    complexity_score = float(np.clip((complexity - 0.08) / 0.30, 0.0, 1.0))

    orb_iou = 0.0
    orb_score = 0.0
    if orb_match is not None:
        orb_iou = compute_box_iou(_candidate_box(refined_loc, (th, tw)), orb_match.bbox)
        orb_support = min(1.0, orb_match.inliers / 12.0)
        orb_score = float(np.clip(0.5 * orb_iou + 0.5 * max(orb_match.score, orb_support), 0.0, 1.0))

    low_texture_mode = distinctiveness < 0.35
    weights: dict[str, float] = {
        "template": 0.50 if low_texture_mode else 0.45,
        "gradient": 0.10 if low_texture_mode else 0.15,
        "chamfer": 0.22 if low_texture_mode else 0.22,
        "edge": 0.08 if low_texture_mode else 0.10,
        "complexity": 0.10 if low_texture_mode else 0.08,
    }
    score_parts: dict[str, float] = {
        "template": template_score,
        "gradient": gradient_score,
        "chamfer": chamfer_score,
        "edge": edge_iou,
        "complexity": complexity_score,
    }
    if orb_match is not None:
        weights["orb"] = 0.10 if low_texture_mode else 0.12
        score_parts["orb"] = orb_score

    total_weight = sum(weights.values()) + 1e-7
    weighted_score = sum(weights[name] * score_parts[name] for name in score_parts) / total_weight

    cue_values = list(score_parts.values())
    cue_agreement = float(np.clip(1.0 - (np.std(cue_values) / 0.25), 0.0, 1.0))
    confidence = float(np.clip(0.9 * weighted_score + 0.1 * cue_agreement, 0.0, 1.0))

    return Candidate(
        loc=refined_loc,
        match_score=template_score,
        complexity=float(complexity),
        combined_score=float(weighted_score),
        final_score=float(weighted_score),
        template_score=template_score,
        gradient_score=gradient_score,
        chamfer_score=chamfer_score,
        edge_iou=edge_iou,
        orb_score=orb_score,
        orb_iou=orb_iou,
        confidence=confidence,
    )
