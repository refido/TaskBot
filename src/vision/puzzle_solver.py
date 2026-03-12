from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from src.vision.puzzle.features import (
    adaptive_edge_mask,
    compute_template_distinctiveness,
    multi_scale_gradient,
)
from src.vision.puzzle.matching import (
    compute_fused_and_chamfer_maps,
    filter_candidates_by_complexity,
    is_uniform_region,
)
from src.vision.puzzle.preprocessing import (
    center_from_mask,
    crop_by_mask,
    ensure_output_dir,
    imread_any,
    scale_template_and_mask,
    to_gray,
)
from src.vision.puzzle.refinement import (
    chamfer_refine,
    local_ncc_refine,
    subpixel_refine,
)
from src.vision.puzzle.types import Candidate, GrayImage, MaskImage, Point, PointF, YRoi
from src.vision.puzzle.visualization import draw_match_visualization


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

    _MAX_K_CANDIDATES: int = 10
    _UNIFORM_EDGE_DENSITY_THRESHOLD: float = 0.02
    _UNIFORM_STD_THRESHOLD: float = 15.0

    def __init__(
        self, gap_image_path: str, bg_image_path: str, output_image_path: str
    ) -> None:
        self.gap_image_path = gap_image_path
        self.bg_image_path = bg_image_path
        self.output_image_path = output_image_path

        # Set during discern_xy (kept for visualization parity with original code).
        self.tpl_center_local: Optional[PointF] = None

    def find_position_of_slide(
        self,
        tpl_gray: GrayImage,
        bg_gray: GrayImage,
        raw_mask: Optional[MaskImage] = None,
        y_roi: YRoi = None,
    ) -> tuple[Point, float]:
        """
        Find position with gradient+chamfer fusion and complexity-based validation.

        For high-texture templates (trees, horizon), use the full
        gradient+complexity pipeline.

        For low-texture templates (sky pieces, very smooth regions),
        relax complexity/uniform filtering and trust correlation+chamfer
        more, otherwise the true sky location gets unfairly penalized.
        """
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

        fused_map, chamfer_sim, bg_gray_for_rank = compute_fused_and_chamfer_maps(
            bg_grad=bg_grad,
            tpl_grad=tpl_grad,
            edge_mask=edge_mask,
            dt_full=dt_full,
            tpl_edges_f=tpl_edges_f,
            bg_gray=bg_gray,
            y_roi=y_roi,
        )

        if low_texture_mode:
            w_grad, w_chamfer = 0.5, 0.5
        else:
            w_grad, w_chamfer = 0.65, 0.35

        combined_map = w_grad * fused_map + w_chamfer * chamfer_sim
        combined_map = cv2.normalize(combined_map, None, 0, 1, cv2.NORM_MINMAX)

        th, tw = tpl_gray.shape[:2]
        candidates = filter_candidates_by_complexity(
            combined_map,
            bg_gray_for_rank,
            (th, tw),
            top_k=self._MAX_K_CANDIDATES,
            use_complexity=not low_texture_mode,
        )

        valid: list[Candidate] = []
        for c in candidates:
            if not low_texture_mode:
                if is_uniform_region(
                    bg_gray_for_rank,
                    c.loc,
                    (th, tw),
                    threshold=self._UNIFORM_EDGE_DENSITY_THRESHOLD,
                    uniform_std_threshold=self._UNIFORM_STD_THRESHOLD,
                ):
                    continue

            y, x = int(c.loc[1]), int(c.loc[0])
            s_grad = float(fused_map[y, x])
            s_cham = float(chamfer_sim[y, x])

            if low_texture_mode:
                final_score = 0.5 * s_grad + 0.5 * s_cham
            else:
                final_score = 0.6 * s_grad + 0.4 * s_cham

            c.final_score = final_score
            valid.append(c)

        if not valid:
            _, max_val, _, max_loc = cv2.minMaxLoc(combined_map)
            best_loc = (int(max_loc[0]), int(max_loc[1]))
            best_score = float(max_val)
        else:
            valid.sort(key=lambda z: float(z.final_score or 0.0), reverse=True)
            best = valid[0]
            best_loc = best.loc
            best_score = float(best.final_score or 0.0)

        loc_sub = subpixel_refine(combined_map, (int(best_loc[0]), int(best_loc[1])))

        if y_roi is not None:
            y0, _ = y_roi
            tl = (loc_sub[0], loc_sub[1] + y0)
        else:
            tl = loc_sub

        refined_xy, _ = chamfer_refine(
            bg_gray,
            tpl_gray,
            (int(round(tl[0])), int(round(tl[1]))),
            search_radius=5,
        )

        refined_xy_ncc, ncc_score = local_ncc_refine(
            bg_gray,
            tpl_gray,
            refined_xy,
            radius=3,
        )

        final_xy = refined_xy_ncc if ncc_score > 0 else refined_xy
        final_x, final_y = int(round(final_xy[0])), int(round(final_xy[1]))

        vis = draw_match_visualization(
            multi_scale_gradient(bg_gray),
            (float(final_x), float(final_y)),
            tw,
            th,
            best_score,
            tpl_center_local=self.tpl_center_local,
        )
        ensure_output_dir(self.output_image_path)
        cv2.imwrite(self.output_image_path, vis)

        return (final_x, final_y), float(best_score)

    def discern_xy(
        self, y_roi: YRoi = None, scales: tuple[float, ...] = (0.95, 1.0, 1.05)
    ) -> tuple[int, int, float, float, tuple[int, int]]:
        """Main solver with complexity filtering."""
        gap_raw = imread_any(self.gap_image_path)
        bg_raw = imread_any(self.bg_image_path)

        gap_cropped, gap_mask = crop_by_mask(
            gap_raw, self._WHITE_BRIGHTNESS_THRESHOLD, self._WHITE_PERCENT_THRESHOLD
        )
        tpl_gray = to_gray(gap_cropped)
        bg_gray = to_gray(bg_raw)

        self.tpl_center_local = center_from_mask(gap_mask)

        best_loc: Point | None = None
        best_score = -1.0
        best_scale: float | None = None
        best_tpl: GrayImage | None = None

        for s in scales:
            tpl_s, mask_s = scale_template_and_mask(tpl_gray, gap_mask, s)
            loc, score = self.find_position_of_slide(
                tpl_s, bg_gray, raw_mask=mask_s, y_roi=y_roi
            )

            if score > best_score:
                best_loc = loc
                best_score = score
                best_scale = s
                best_tpl = tpl_s

        if best_loc is None or best_tpl is None or best_scale is None:
            raise RuntimeError("No valid puzzle match found")

        refined_xy, _ = chamfer_refine(
            bg_gray,
            best_tpl,
            (int(round(best_loc[0])), int(round(best_loc[1]))),
            search_radius=5,
        )

        th, tw = best_tpl.shape[:2]
        return (
            int(round(refined_xy[0])),
            int(round(refined_xy[1])),
            float(best_score),
            float(best_scale),
            (int(tw), int(th)),
        )
