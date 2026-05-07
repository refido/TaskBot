from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Iterator, Optional

import cv2
import numpy as np

from src.vision.puzzle.features import (
    adaptive_edge_mask,
    compute_template_distinctiveness,
    multi_scale_gradient,
)
from src.vision.puzzle.matching import (
    compute_fused_and_chamfer_maps,
    compute_orb_match,
    extract_top_peak_candidates,
    filter_candidates_by_complexity,
    is_uniform_region,
    match_maps_fused,
    non_max_suppress_candidates,
    rescore_candidate,
)
from src.vision.puzzle.preprocessing import (
    build_match_mask,
    center_from_mask,
    compute_processing_scale,
    crop_by_mask,
    ensure_output_dir,
    imread_any,
    preprocess_for_matching,
    resize_gray,
    resize_mask,
    scale_template_and_mask,
    scale_y_roi,
    to_gray,
)
from src.vision.puzzle.refinement import (
    chamfer_refine,
    ecc_refine,
    local_ncc_refine,
    subpixel_refine,
)
from src.vision.puzzle.types import (
    Candidate,
    FloatMap,
    GrayImage,
    ImageArray,
    MaskImage,
    Point,
    PointF,
    YRoi,
)
from src.vision.puzzle.visualization import draw_match_visualization


@dataclass(slots=True)
class _BackgroundContext:
    gray: GrayImage
    match: GrayImage
    grad: GrayImage
    edges: MaskImage
    distance_transform: FloatMap


@dataclass(slots=True)
class _TemplateContext:
    gray: GrayImage
    mask: MaskImage | None
    match: GrayImage
    grad: GrayImage
    edge_mask: MaskImage
    edges: MaskImage
    edges_f: FloatMap
    distinctiveness: float
    low_texture_mode: bool


class PuzzleSolver:
    """
    Puzzle gap locator for slider CAPTCHA.

    External API preserved:
    - __init__(gap_image_path, bg_image_path, output_image_path)
    - discern_xy(y_roi=None, scales=(...)) -> (x, y, score, scale, (tw, th))
    - find_position_of_slide(tpl_gray, bg_gray, raw_mask=None, y_roi=None) -> ((x, y), score)
    """

    _WHITE_BRIGHTNESS_THRESHOLD: int = 240
    _WHITE_PERCENT_THRESHOLD: float = 70.0

    _MAX_K_CANDIDATES: int = 14
    _TOP_REFINED_CANDIDATES: int = 3
    _CANDIDATE_NMS_IOU: float = 0.35
    _MAX_PROCESSING_SIDE: int = 420
    _UNIFORM_EDGE_DENSITY_THRESHOLD: float = 0.02
    _UNIFORM_STD_THRESHOLD: float = 15.0

    _LEGACY_FALLBACK_SCORE_THRESHOLD: float = 0.62
    _LEGACY_FALLBACK_MARGIN_THRESHOLD: float = 0.05

    def __init__(
        self,
        gap_image_path: str,
        bg_image_path: str,
        output_image_path: str,
        *,
        gap_image: ImageArray | None = None,
        bg_image: ImageArray | None = None,
        enable_timing: bool = True,
    ) -> None:
        self.gap_image_path = gap_image_path
        self.bg_image_path = bg_image_path
        self.output_image_path = output_image_path
        self.gap_image = gap_image
        self.bg_image = bg_image
        self.enable_timing = enable_timing
        self.timing_metrics: dict[str, float] = {}

        self.tpl_center_local: Optional[PointF] = None

    @contextmanager
    def _timed(self, stage: str) -> Iterator[None]:
        if not self.enable_timing:
            yield
            return

        started = perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (perf_counter() - started) * 1000.0
            self.timing_metrics[stage] = self.timing_metrics.get(stage, 0.0) + elapsed_ms

    def _load_image_inputs(self) -> tuple[ImageArray, ImageArray]:
        with self._timed("io.load_images"):
            gap_raw = (
                self.gap_image
                if self.gap_image is not None
                else imread_any(self.gap_image_path)
            )
            bg_raw = (
                self.bg_image
                if self.bg_image is not None
                else imread_any(self.bg_image_path)
            )
        return gap_raw, bg_raw

    @staticmethod
    def _normalize_map(res_map: np.ndarray) -> np.ndarray:
        res_map = res_map.astype(np.float32)
        if res_map.size == 0:
            return res_map

        min_val = float(np.min(res_map))
        max_val = float(np.max(res_map))
        if max_val - min_val < 1e-6:
            return np.zeros_like(res_map, dtype=np.float32)

        return cv2.normalize(res_map, None, 0.0, 1.0, cv2.NORM_MINMAX).astype(
            np.float32
        )

    @staticmethod
    def _local_peak_score(res_map: np.ndarray, loc: Point, radius: int = 1) -> float:
        x, y = int(loc[0]), int(loc[1])
        y0 = max(0, y - radius)
        y1 = min(res_map.shape[0], y + radius + 1)
        x0 = max(0, x - radius)
        x1 = min(res_map.shape[1], x + radius + 1)
        patch = res_map[y0:y1, x0:x1]
        if patch.size == 0:
            return 0.0
        return float(np.max(patch))

    def _prepare_background_context(self, bg_gray: GrayImage) -> _BackgroundContext:
        with self._timed("preprocess.background.match"):
            bg_match = preprocess_for_matching(bg_gray)
        with self._timed("preprocess.background.gradient"):
            bg_grad = multi_scale_gradient(bg_match)
        with self._timed("preprocess.background.edges_dt"):
            bg_edges = adaptive_edge_mask(bg_match, None)
            inv_full = (bg_edges == 0).astype(np.uint8) * 255
            dt_full = cv2.distanceTransform(inv_full, cv2.DIST_L2, 5).astype(
                np.float32
            )

        return _BackgroundContext(
            gray=bg_gray,
            match=bg_match,
            grad=bg_grad,
            edges=bg_edges,
            distance_transform=dt_full,
        )

    def _prepare_template_context(
        self, tpl_gray: GrayImage, raw_mask: MaskImage | None
    ) -> _TemplateContext:
        with self._timed("preprocess.template.distinctiveness"):
            distinctiveness = compute_template_distinctiveness(tpl_gray)
        with self._timed("preprocess.template.match"):
            tpl_match = preprocess_for_matching(tpl_gray)
        with self._timed("preprocess.template.gradient_edges"):
            tpl_grad = multi_scale_gradient(tpl_match)
            tpl_edges = adaptive_edge_mask(tpl_match, raw_mask)
            tpl_edges_f = (tpl_edges > 0).astype(np.float32)

        return _TemplateContext(
            gray=tpl_gray,
            mask=raw_mask,
            match=tpl_match,
            grad=tpl_grad,
            edge_mask=tpl_edges,
            edges=tpl_edges,
            edges_f=tpl_edges_f,
            distinctiveness=distinctiveness,
            low_texture_mode=distinctiveness < 0.35,
        )

    @staticmethod
    def _point_template_score(
        bg_gray: GrayImage,
        tpl_gray: GrayImage,
        loc: Point,
        mask: MaskImage | None = None,
        match_mask: MaskImage | None = None,
    ) -> float:
        th, tw = tpl_gray.shape[:2]
        x, y = int(loc[0]), int(loc[1])
        if (
            x < 0
            or y < 0
            or x + tw > bg_gray.shape[1]
            or y + th > bg_gray.shape[0]
        ):
            return -1.0

        roi = bg_gray[y : y + th, x : x + tw]
        if match_mask is None:
            match_mask = build_match_mask(mask, erode_iterations=1)

        if match_mask is not None:
            try:
                corr = float(
                    cv2.matchTemplate(
                        roi, tpl_gray, cv2.TM_CCORR_NORMED, mask=match_mask
                    )[0, 0]
                )
                sqdiff = float(
                    1.0
                    - cv2.matchTemplate(
                        roi, tpl_gray, cv2.TM_SQDIFF_NORMED, mask=match_mask
                    )[0, 0]
                )
                return 0.60 * corr + 0.40 * sqdiff
            except cv2.error:
                pass

        return float(cv2.matchTemplate(roi, tpl_gray, cv2.TM_CCOEFF_NORMED)[0, 0])

    @staticmethod
    def _legacy_match_maps_fused(
        bg_gray: GrayImage, tpl_gray: GrayImage, tpl_mask: MaskImage | None
    ) -> np.ndarray:
        mask = None
        if tpl_mask is not None:
            mask = tpl_mask.astype(np.uint8)
            if mask.max() <= 1:
                mask = (mask > 0).astype(np.uint8) * 255

        if mask is not None:
            res_corr = cv2.matchTemplate(
                bg_gray, tpl_gray, cv2.TM_CCORR_NORMED, mask=mask
            )
        else:
            res_corr = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCORR_NORMED)

        res_coef = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        res_sqdiff = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_SQDIFF_NORMED)
        res_sqdiff = 1.0 - res_sqdiff

        res_corr = cv2.normalize(res_corr, None, 0, 1, cv2.NORM_MINMAX)
        res_coef = cv2.normalize(res_coef, None, 0, 1, cv2.NORM_MINMAX)
        res_sqdiff = cv2.normalize(res_sqdiff, None, 0, 1, cv2.NORM_MINMAX)

        max_corr = float(res_corr.max())
        max_coef = float(res_coef.max())
        max_sqdiff = float(res_sqdiff.max())

        total = max_corr + max_coef + max_sqdiff + 1e-7
        w_corr = max(0.3, max_corr / total)
        w_coef = max(0.3, max_coef / total)
        w_sqdiff = max(0.2, max_sqdiff / total)

        total_w = w_corr + w_coef + w_sqdiff
        w_corr /= total_w
        w_coef /= total_w
        w_sqdiff /= total_w

        return (
            w_corr * res_corr + w_coef * res_coef + w_sqdiff * res_sqdiff
        ).astype(np.float32)

    def _refine_candidate_loc(
        self,
        bg_gray: GrayImage,
        tpl_gray: GrayImage,
        coarse_xy: Point,
        score_map: np.ndarray,
        raw_mask: MaskImage | None = None,
        search_radius: int = 4,
        score_offset: Point = (0, 0),
    ) -> tuple[Point, float, float]:
        local_x = int(
            np.clip(
                coarse_xy[0] - score_offset[0],
                0,
                max(0, score_map.shape[1] - 1),
            )
        )
        local_y = int(
            np.clip(
                coarse_xy[1] - score_offset[1],
                0,
                max(0, score_map.shape[0] - 1),
            )
        )
        loc_sub = subpixel_refine(score_map, (local_x, local_y))

        coarse_from_sub = (
            int(round(loc_sub[0] + score_offset[0])),
            int(round(loc_sub[1] + score_offset[1])),
        )
        chamfer_xy, _ = chamfer_refine(
            bg_gray,
            tpl_gray,
            coarse_from_sub,
            search_radius=search_radius,
            mask=raw_mask,
        )

        ecc_xy, ecc_score = ecc_refine(
            bg_gray,
            tpl_gray,
            chamfer_xy,
            mask=raw_mask,
        )
        ecc_xy_int = (int(round(ecc_xy[0])), int(round(ecc_xy[1])))

        ncc_xy, ncc_score = local_ncc_refine(
            bg_gray,
            tpl_gray,
            ecc_xy_int,
            radius=2,
            mask=raw_mask,
        )

        if ncc_score > 0:
            final_xy = ncc_xy
        else:
            final_xy = ecc_xy_int

        return final_xy, float(max(0.0, ecc_score)), float(max(0.0, ncc_score))

    def _refine_original_resolution(
        self,
        bg_gray: GrayImage,
        tpl_gray: GrayImage,
        raw_mask: MaskImage | None,
        coarse_xy: Point,
        base_score: float,
        tpl_match: GrayImage | None = None,
    ) -> tuple[Point, float]:
        th, tw = tpl_gray.shape[:2]
        radius = 6

        x0 = max(0, coarse_xy[0] - radius)
        y0 = max(0, coarse_xy[1] - radius)
        x1 = min(bg_gray.shape[1], coarse_xy[0] + tw + radius)
        y1 = min(bg_gray.shape[0], coarse_xy[1] + th + radius)

        if y1 - y0 < th or x1 - x0 < tw:
            return coarse_xy, float(base_score)

        roi = bg_gray[y0:y1, x0:x1]
        with self._timed("refine_original.preprocess"):
            roi_match = preprocess_for_matching(roi)
            if tpl_match is None:
                tpl_match = preprocess_for_matching(tpl_gray)

        with self._timed("refine_original.match_map"):
            local_map = match_maps_fused(roi_match, tpl_match, raw_mask)
            _min_val, max_val, _min_loc, local_best = cv2.minMaxLoc(local_map)
        loc_sub = subpixel_refine(local_map, (int(local_best[0]), int(local_best[1])))
        coarse_local_xy = (int(round(x0 + loc_sub[0])), int(round(y0 + loc_sub[1])))

        with self._timed("refine_original.local_refine"):
            refined_xy, ecc_score, ncc_score = self._refine_candidate_loc(
                bg_gray,
                tpl_gray,
                coarse_local_xy,
                self._normalize_map(local_map),
                raw_mask=raw_mask,
                search_radius=4,
                score_offset=(x0, y0),
            )

        with self._timed("refine_original.validate_scores"):
            match_mask = build_match_mask(raw_mask, erode_iterations=1)
            coarse_score = self._point_template_score(
                bg_gray, tpl_gray, coarse_xy, raw_mask, match_mask=match_mask
            )
            refined_template_score = self._point_template_score(
                bg_gray, tpl_gray, refined_xy, raw_mask, match_mask=match_mask
            )
        if (
            refined_template_score < coarse_score + 0.01
            and abs(refined_xy[0] - coarse_xy[0]) > max(4, tw // 8)
        ) or refined_template_score < coarse_score:
            refined_xy = coarse_xy
            refined_template_score = coarse_score

        final_score = float(
            np.clip(
                0.60 * base_score
                + 0.20 * max(float(max_val), max(0.0, refined_template_score))
                + 0.08 * ecc_score
                + 0.07 * ncc_score,
                0.0,
                1.0,
            )
        )
        return refined_xy, final_score

    def _legacy_find_position(
        self,
        tpl_gray: GrayImage,
        bg_gray: GrayImage,
        raw_mask: MaskImage | None = None,
        y_roi: YRoi = None,
    ) -> tuple[Point, float]:
        distinctiveness = compute_template_distinctiveness(tpl_gray)
        low_texture_mode = distinctiveness < 0.35

        tpl_grad = multi_scale_gradient(tpl_gray)
        bg_grad = multi_scale_gradient(bg_gray)

        edge_mask = adaptive_edge_mask(tpl_gray, raw_mask)
        bg_edges_full = adaptive_edge_mask(bg_gray, None)
        inv_full = (bg_edges_full == 0).astype(np.uint8) * 255
        dt_full = cv2.distanceTransform(inv_full, cv2.DIST_L2, 5).astype(np.float32)

        tpl_edges = adaptive_edge_mask(tpl_gray, None)
        tpl_edges_f = (tpl_edges > 0).astype(np.float32)

        if y_roi is not None:
            y0, y1 = y_roi
            fused_map = self._legacy_match_maps_fused(
                bg_grad[y0:y1, :], tpl_grad, edge_mask
            )
            res_dt = cv2.matchTemplate(dt_full[y0:y1, :], tpl_edges_f, cv2.TM_SQDIFF)
            res_dt = cv2.normalize(res_dt, None, 0, 1, cv2.NORM_MINMAX)
            chamfer_sim = 1.0 - res_dt
            bg_gray_for_rank = bg_gray[y0:y1, :]
        else:
            y0 = 0
            fused_map = self._legacy_match_maps_fused(bg_grad, tpl_grad, edge_mask)
            res_dt = cv2.matchTemplate(dt_full, tpl_edges_f, cv2.TM_SQDIFF)
            res_dt = cv2.normalize(res_dt, None, 0, 1, cv2.NORM_MINMAX)
            chamfer_sim = 1.0 - res_dt
            bg_gray_for_rank = bg_gray

        if low_texture_mode:
            w_grad, w_chamfer = 0.50, 0.50
        else:
            w_grad, w_chamfer = 0.65, 0.35

        combined_map = self._normalize_map(w_grad * fused_map + w_chamfer * chamfer_sim)

        th, tw = tpl_gray.shape[:2]
        candidates = filter_candidates_by_complexity(
            combined_map,
            bg_gray_for_rank,
            (th, tw),
            top_k=self._MAX_K_CANDIDATES,
            use_complexity=not low_texture_mode,
        )

        valid: list[Candidate] = []
        for candidate in candidates:
            if (
                not low_texture_mode
                and is_uniform_region(
                    bg_gray_for_rank,
                    candidate.loc,
                    (th, tw),
                    threshold=self._UNIFORM_EDGE_DENSITY_THRESHOLD,
                    uniform_std_threshold=self._UNIFORM_STD_THRESHOLD,
                )
            ):
                continue

            y, x = int(candidate.loc[1]), int(candidate.loc[0])
            s_grad = float(fused_map[y, x])
            s_chamfer = float(chamfer_sim[y, x])
            candidate.final_score = (
                0.50 * s_grad + 0.50 * s_chamfer
                if low_texture_mode
                else 0.60 * s_grad + 0.40 * s_chamfer
            )
            valid.append(candidate)

        if not valid:
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(combined_map)
            best_loc = (int(max_loc[0]), int(max_loc[1]))
            best_score = float(max_val)
        else:
            valid.sort(key=lambda item: float(item.final_score or 0.0), reverse=True)
            best_loc = valid[0].loc
            best_score = float(valid[0].final_score or 0.0)

        loc_sub = subpixel_refine(combined_map, (int(best_loc[0]), int(best_loc[1])))

        if y_roi is not None:
            y0, _y1 = y_roi
            coarse_xy = (int(round(loc_sub[0])), int(round(loc_sub[1] + y0)))
        else:
            y0 = 0
            coarse_xy = (int(round(loc_sub[0])), int(round(loc_sub[1])))

        refined_loc, _ = chamfer_refine(
            bg_gray,
            tpl_gray,
            coarse_xy,
            search_radius=5,
            mask=None,
        )

        refined_loc_ncc, ncc_score = local_ncc_refine(
            bg_gray,
            tpl_gray,
            refined_loc,
            radius=3,
            mask=None,
        )
        final_loc = refined_loc_ncc if ncc_score > 0 else refined_loc
        final_score = float(
            np.clip(0.82 * best_score + 0.18 * max(0.0, ncc_score), 0.0, 1.0)
        )
        return final_loc, final_score

    def find_position_of_slide(
        self,
        tpl_gray: GrayImage,
        bg_gray: GrayImage,
        raw_mask: Optional[MaskImage] = None,
        y_roi: YRoi = None,
    ) -> tuple[Point, float]:
        """
        Find position using coarse candidate generation plus multi-cue rescoring.

        The detector first builds a candidate pool from fast matchers and ORB,
        then reranks those locations with stronger masked/template/edge signals,
        then refines the top candidates with subpixel, chamfer, ECC, and NCC.
        """
        bg_context = self._prepare_background_context(bg_gray)
        tpl_context = self._prepare_template_context(tpl_gray, raw_mask)
        return self._find_position_prepared(bg_context, tpl_context, y_roi)

    def _find_position_prepared(
        self,
        bg_context: _BackgroundContext,
        tpl_context: _TemplateContext,
        y_roi: YRoi = None,
    ) -> tuple[Point, float]:
        tpl_match = tpl_context.match
        raw_mask = tpl_context.mask
        low_texture_mode = tpl_context.low_texture_mode

        if y_roi is not None:
            y0, y1 = y_roi
            bg_match_search = bg_context.match[y0:y1, :]
            bg_edges_search = bg_context.edges[y0:y1, :]
        else:
            y0 = 0
            bg_match_search = bg_context.match
            bg_edges_search = bg_context.edges

        with self._timed("match.template_map"):
            template_map = match_maps_fused(bg_match_search, tpl_match, raw_mask)
        with self._timed("match.gradient_chamfer_maps"):
            fused_map, chamfer_sim, bg_gray_for_rank = compute_fused_and_chamfer_maps(
                bg_grad=bg_context.grad,
                tpl_grad=tpl_context.grad,
                edge_mask=tpl_context.edge_mask,
                dt_full=bg_context.distance_transform,
                tpl_edges_f=tpl_context.edges_f,
                bg_gray=bg_context.match,
                y_roi=y_roi,
            )

        if low_texture_mode:
            w_tpl, w_grad, w_chamfer = 0.45, 0.20, 0.35
        else:
            w_tpl, w_grad, w_chamfer = 0.34, 0.33, 0.33

        combined_map = self._normalize_map(
            w_tpl * template_map + w_grad * fused_map + w_chamfer * chamfer_sim
        )

        th, tw = tpl_match.shape[:2]
        candidate_pool: list[Candidate] = []
        suppression_radius = max(6, min(tw, th) // 5)

        with self._timed("candidate.extract"):
            for res_map, top_k in (
                (template_map, 6),
                (fused_map, 5),
                (chamfer_sim, 5),
                (combined_map, 8),
            ):
                candidate_pool.extend(
                    extract_top_peak_candidates(
                        res_map,
                        top_k=top_k,
                        suppression_radius=suppression_radius,
                    )
                )

            candidate_pool.extend(
                filter_candidates_by_complexity(
                    combined_map,
                    bg_gray_for_rank,
                    (th, tw),
                    top_k=6,
                    use_complexity=not low_texture_mode,
                )
            )

        with self._timed("match.orb"):
            orb_match = compute_orb_match(bg_match_search, tpl_match, raw_mask)
        if orb_match is not None:
            candidate_pool.append(
                Candidate(
                    loc=orb_match.loc,
                    match_score=orb_match.score,
                    combined_score=orb_match.score,
                )
            )

        candidate_pool = non_max_suppress_candidates(
            candidate_pool,
            (th, tw),
            iou_threshold=self._CANDIDATE_NMS_IOU,
            limit=self._MAX_K_CANDIDATES,
        )

        rescored: list[Candidate] = []
        with self._timed("candidate.rescore_initial"):
            for candidate in candidate_pool:
                rescored_candidate = rescore_candidate(
                    bg_gray=bg_match_search,
                    tpl_gray=tpl_match,
                    tpl_mask=raw_mask,
                    template_map=template_map,
                    gradient_map=fused_map,
                    chamfer_map=chamfer_sim,
                    bg_edges=bg_edges_search,
                    tpl_edges=tpl_context.edges,
                    bg_gray_for_rank=bg_gray_for_rank,
                    initial_loc=candidate.loc,
                    orb_match=orb_match,
                    distinctiveness=tpl_context.distinctiveness,
                    search_radius=4,
                )

                if (
                    not low_texture_mode
                    and is_uniform_region(
                        bg_gray_for_rank,
                        rescored_candidate.loc,
                        (th, tw),
                        threshold=self._UNIFORM_EDGE_DENSITY_THRESHOLD,
                        uniform_std_threshold=self._UNIFORM_STD_THRESHOLD,
                    )
                ):
                    continue

                rescored.append(rescored_candidate)

        if not rescored:
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(combined_map)
            best_loc = (int(max_loc[0]), int(max_loc[1]))
            final_loc = (best_loc[0], best_loc[1] + y0)
            return final_loc, float(max_val)

        rescored = non_max_suppress_candidates(
            rescored,
            (th, tw),
            iou_threshold=self._CANDIDATE_NMS_IOU,
            limit=self._TOP_REFINED_CANDIDATES,
        )

        refined_candidates: list[Candidate] = []
        with self._timed("candidate.refine_top"):
            for candidate in rescored:
                refined_xy, ecc_score, ncc_score = self._refine_candidate_loc(
                    bg_match_search,
                    tpl_match,
                    candidate.loc,
                    combined_map,
                    raw_mask=raw_mask,
                    search_radius=4,
                )

                refined_candidate = rescore_candidate(
                    bg_gray=bg_match_search,
                    tpl_gray=tpl_match,
                    tpl_mask=raw_mask,
                    template_map=template_map,
                    gradient_map=fused_map,
                    chamfer_map=chamfer_sim,
                    bg_edges=bg_edges_search,
                    tpl_edges=tpl_context.edges,
                    bg_gray_for_rank=bg_gray_for_rank,
                    initial_loc=refined_xy,
                    orb_match=orb_match,
                    distinctiveness=tpl_context.distinctiveness,
                    search_radius=1,
                )
                refined_candidate.final_score = float(
                    np.clip(
                        0.78 * refined_candidate.confidence
                        + 0.12 * ecc_score
                        + 0.10 * ncc_score,
                        0.0,
                        1.0,
                    )
                )
                refined_candidate.confidence = float(refined_candidate.final_score)
                refined_candidates.append(refined_candidate)

        refined_candidates.sort(
            key=lambda candidate: float(candidate.final_score or 0.0), reverse=True
        )
        best = refined_candidates[0]
        runner_up_score = (
            float(refined_candidates[1].final_score or 0.0)
            if len(refined_candidates) > 1
            else 0.0
        )

        margin = max(0.0, float(best.final_score or 0.0) - runner_up_score)
        best_score = float(
            np.clip(
                0.90 * float(best.final_score or 0.0)
                + 0.10 * min(1.0, margin / 0.12),
                0.0,
                1.0,
            )
        )

        final_loc = best.loc
        if y_roi is not None:
            final_loc = (final_loc[0], final_loc[1] + y0)

        new_loc_search = (final_loc[0], final_loc[1] - y0)
        new_template_support = self._local_peak_score(template_map, new_loc_search, 1)
        new_selection_score = 0.65 * best_score + 0.35 * new_template_support

        should_check_legacy = (
            best_score < self._LEGACY_FALLBACK_SCORE_THRESHOLD
            or margin < self._LEGACY_FALLBACK_MARGIN_THRESHOLD
            or new_template_support < 0.35
        )
        if not should_check_legacy:
            return final_loc, float(np.clip(new_selection_score, 0.0, 1.0))

        with self._timed("match.legacy_fallback"):
            legacy_loc, legacy_score = self._legacy_find_position(
                tpl_context.gray,
                bg_context.gray,
                raw_mask=raw_mask,
                y_roi=y_roi,
            )

        legacy_loc_search = (legacy_loc[0], legacy_loc[1] - y0)
        legacy_template_support = self._local_peak_score(
            template_map, legacy_loc_search, 1
        )
        legacy_selection_score = 0.65 * legacy_score + 0.35 * legacy_template_support

        if (
            legacy_selection_score > new_selection_score + 0.02
            or (
                abs(legacy_loc[0] - final_loc[0]) > max(4, tw // 8)
                and legacy_template_support > new_template_support + 0.05
                and legacy_score >= best_score - 0.03
            )
        ):
            return legacy_loc, float(np.clip(legacy_selection_score, 0.0, 1.0))

        return final_loc, float(np.clip(new_selection_score, 0.0, 1.0))

    def discern_xy(
        self,
        y_roi: YRoi = None,
        scales: tuple[float, ...] = (0.95, 1.0, 1.05),
    ) -> tuple[int, int, float, float, tuple[int, int]]:
        """Main solver with preprocessing, coarse localization, and final refinement."""
        self.timing_metrics.clear()
        total_started = perf_counter()
        gap_raw, bg_raw = self._load_image_inputs()

        with self._timed("preprocess.crop_and_gray"):
            gap_cropped, gap_mask = crop_by_mask(
                gap_raw, self._WHITE_BRIGHTNESS_THRESHOLD, self._WHITE_PERCENT_THRESHOLD
            )
            tpl_gray_raw = to_gray(gap_cropped)
            bg_gray_raw = to_gray(bg_raw)

            self.tpl_center_local = center_from_mask(gap_mask)

        with self._timed("preprocess.resize"):
            processing_scale = compute_processing_scale(
                bg_gray_raw.shape[:2], max_processing_side=self._MAX_PROCESSING_SIDE
            )
            bg_gray_proc = resize_gray(bg_gray_raw, processing_scale)
            tpl_gray_proc = resize_gray(tpl_gray_raw, processing_scale)
            gap_mask_proc = resize_mask(gap_mask, processing_scale)
            y_roi_proc = scale_y_roi(y_roi, processing_scale)

        bg_context = self._prepare_background_context(bg_gray_proc)

        best_loc_proc: Point | None = None
        best_score = -1.0
        best_scale: float | None = None

        for scale in scales:
            scale_key = f"{scale:.3f}".rstrip("0").rstrip(".")
            with self._timed(f"scale.{scale_key}.resize_template"):
                tpl_s_proc, mask_s_proc = scale_template_and_mask(
                    tpl_gray_proc, gap_mask_proc, scale
                )
            tpl_context = self._prepare_template_context(tpl_s_proc, mask_s_proc)
            with self._timed(f"scale.{scale_key}.locate"):
                loc_proc, score = self._find_position_prepared(
                    bg_context,
                    tpl_context,
                    y_roi=y_roi_proc,
                )

            if score > best_score:
                best_loc_proc = loc_proc
                best_score = score
                best_scale = scale

        if best_loc_proc is None or best_scale is None:
            raise RuntimeError("No valid puzzle match found")

        with self._timed("refine_original.scale_template"):
            best_tpl_orig, best_mask_orig = scale_template_and_mask(
                tpl_gray_raw, gap_mask, best_scale
            )
            best_tpl_orig_match = preprocess_for_matching(best_tpl_orig)

        coarse_xy_orig = (
            int(round(best_loc_proc[0] / processing_scale)),
            int(round(best_loc_proc[1] / processing_scale)),
        )

        refined_xy, refined_score = self._refine_original_resolution(
            bg_gray_raw,
            best_tpl_orig,
            best_mask_orig,
            coarse_xy_orig,
            best_score,
            tpl_match=best_tpl_orig_match,
        )

        th, tw = best_tpl_orig.shape[:2]
        tpl_center_for_vis = None
        if self.tpl_center_local is not None:
            tpl_center_for_vis = (
                float(self.tpl_center_local[0] * best_scale),
                float(self.tpl_center_local[1] * best_scale),
            )

        with self._timed("debug.write_visualization"):
            vis = draw_match_visualization(
                bg_gray_raw,
                (float(refined_xy[0]), float(refined_xy[1])),
                tw,
                th,
                refined_score,
                tpl_center_local=tpl_center_for_vis,
            )
            ensure_output_dir(self.output_image_path)
            cv2.imwrite(self.output_image_path, vis)

        if self.enable_timing:
            self.timing_metrics["total"] = (perf_counter() - total_started) * 1000.0

        return (
            int(round(refined_xy[0])),
            int(round(refined_xy[1])),
            float(refined_score),
            float(best_scale),
            (int(tw), int(th)),
        )
