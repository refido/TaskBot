from pathlib import Path

import cv2
import numpy as np


class PuzzleSolver:
    def __init__(self, gap_image_path, bg_image_path, output_image_path):
        self.gap_image_path = gap_image_path
        self.bg_image_path = bg_image_path
        self.output_image_path = output_image_path

    def _imread_any(self, path):
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)  # keep alpha if present
        if img is None:
            raise FileNotFoundError(f"Cannot read image file: {path}")
        return img

    def _to_gray(self, img):
        if img.ndim == 2:
            return img
        if img.shape[2] == 4:
            return cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def _crop_by_mask(self, img):
        # Prefer alpha if available
        if img.ndim == 3 and img.shape[2] == 4:
            alpha = img[:, :, 3]
            mask = (alpha > 5).astype(np.uint8) * 255
        else:
            # Non-white mask in HSV (white ≈ high V, low S)
            bgr = (
                img
                if (img.ndim == 3 and img.shape[2] >= 3)
                else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            )
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            h, s, v = cv2.split(hsv)
            white = (v > 245) & (s < 20)
            mask = (~white).astype(np.uint8) * 255

        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1
        )
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1
        )
        ys, xs = np.where(mask > 0)
        if len(xs) == 0 or len(ys) == 0:
            return img, mask  # nothing to crop
        x0, x1 = xs.min(), xs.max()
        y0, y1 = ys.min(), ys.max()
        return img[y0 : y1 + 1, x0 : x1 + 1], mask[y0 : y1 + 1, x0 : x1 + 1]

    def _gradient_map(self, gray):
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        mag = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        return mag

    def _find_match(self, tpl, bg, mask=None):
        # TM_CCORR_NORMED supports mask (OpenCV >= 4.2)
        method = cv2.TM_CCORR_NORMED
        res = (
            cv2.matchTemplate(bg, tpl, method, mask=mask)
            if mask is not None
            else cv2.matchTemplate(bg, tpl, method)
        )
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        return max_loc, max_val, res

    def _match_maps_fused(self, bg_gray, tpl_gray, tpl_mask):
        """
        Build two response maps:
        - TM_CCORR_NORMED with a mask (supported)
        - TM_CCOEFF_NORMED without a mask (illumination-robust)
        Then fuse them (0.6/0.4) and find the best match.
        """
        # Ensure mask type/size is valid for masked matching (same WxH, 8-bit)
        m = None
        if tpl_mask is not None:
            m = tpl_mask
            if m.dtype != np.uint8:
                m = m.astype(np.uint8)
            if m.max() <= 1:
                m = (m > 0).astype(np.uint8) * 255

        res_corr = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCORR_NORMED, mask=m)
        res_coef = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)

        # Normalize and fuse
        res_corr = cv2.normalize(res_corr, None, 0, 1, cv2.NORM_MINMAX)
        res_coef = cv2.normalize(res_coef, None, 0, 1, cv2.NORM_MINMAX)
        fused = 0.6 * res_corr + 0.4 * res_coef

        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(fused)
        return fused, max_loc, float(max_val)

    def _chamfer_refine(self, bg_gray, tpl_gray, coarse_xy, search_radius=24):
        """
        Refine the coarse match by aligning edges using chamfer distance:
        - Build a distance transform on inverse edges of a small ROI
        - Slide the template's edge mask over the DT with TM_SQDIFF (minimize)
        """
        th, tw = tpl_gray.shape[:2]
        # ROI around coarse hit
        x0 = max(0, coarse_xy[0] - search_radius)
        y0 = max(0, coarse_xy[1] - search_radius)
        x1 = min(bg_gray.shape[1], coarse_xy[0] + tw + search_radius)
        y1 = min(bg_gray.shape[0], coarse_xy[1] + th + search_radius)
        roi = bg_gray[y0:y1, x0:x1]

        # Bail out if ROI is smaller than template
        if roi.shape[0] < th or roi.shape[1] < tw:
            return coarse_xy, float("inf")

        # Edges and distance transform (inverse edges -> distance to nearest edge)
        roi_edges = cv2.Canny(roi, 50, 150)
        inv = (roi_edges == 0).astype(np.uint8) * 255
        dt = cv2.distanceTransform(inv, cv2.DIST_L2, 3).astype(np.float32)

        tpl_edges = (cv2.Canny(tpl_gray, 50, 150) > 0).astype(np.float32)

        # Minimize chamfer cost with SQDIFF on DT field
        res = cv2.matchTemplate(dt, tpl_edges, cv2.TM_SQDIFF)
        min_val, _, min_loc, _ = cv2.minMaxLoc(res)
        refined = (x0 + min_loc[0], y0 + min_loc[1])
        return refined, float(min_val)

    def find_position_of_slide(self, tpl_gray, bg_gray, raw_mask=None, y_roi=None):
        """
        Compute gradient maps, build a tight binary mask over template edges,
        run fused masked/unmasked template matching, and return the coarse (x,y) and score.
        """
        # Gradients to reduce lighting bias
        tpl_grad = self._gradient_map(tpl_gray)
        bg_grad = self._gradient_map(bg_gray)

        # Edge-focused mask (combine raw mask, if any, with Canny)
        edge_mask = cv2.Canny(tpl_gray, 50, 150)
        if raw_mask is not None:
            rm = (raw_mask > 0).astype(np.uint8) * 255
            tpl_mask = cv2.bitwise_and(edge_mask, rm)
        else:
            tpl_mask = edge_mask

        # Optional vertical ROI
        if y_roi is not None:
            y0, y1 = y_roi
            bg_grad_roi = bg_grad[y0:y1, :]
            fused, loc, fused_score = self._match_maps_fused(
                bg_grad_roi, tpl_grad, tpl_mask
            )
            tl = (loc[0], loc[1] + y0)
        else:
            fused, loc, fused_score = self._match_maps_fused(
                bg_grad, tpl_grad, tpl_mask
            )
            tl = loc

        th, tw = tpl_grad.shape[:2]
        br = (tl[0] + tw, tl[1] + th)

        # Debug visualization on gradient image
        vis = cv2.cvtColor(bg_grad, cv2.COLOR_GRAY2BGR)
        cv2.rectangle(vis, tl, br, (0, 0, 255), 2)
        Path(self.output_image_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(self.output_image_path, vis)

        return (tl[0], tl[1]), fused_score

    def discern(self, y_roi=None, scales=(1.0, 0.95, 1.05)):
        """
        Multi-scale coarse search using fused template matching on gradients,
        followed by a single chamfer refinement around the best scale/location.
        Returns (x, score) for backward compatibility with your caller.
        """
        gap_raw = self._imread_any(self.gap_image_path)
        bg_raw = self._imread_any(self.bg_image_path)

        gap_cropped, gap_mask = self._crop_by_mask(gap_raw)
        tpl_gray = self._to_gray(gap_cropped)
        bg_gray = self._to_gray(bg_raw)

        best = (None, -1.0, None, None)  # (xy, score, scale, tpl_at_scale)

        for s in scales:
            if s != 1.0:
                th, tw = tpl_gray.shape[:2]
                new_size = (max(1, int(tw * s)), max(1, int(th * s)))
                tpl_s = cv2.resize(tpl_gray, new_size, interpolation=cv2.INTER_AREA)
                mask_s = (
                    cv2.resize(gap_mask, new_size, interpolation=cv2.INTER_NEAREST)
                    if gap_mask is not None
                    else None
                )
            else:
                tpl_s, mask_s = tpl_gray, gap_mask

            loc, score = self.find_position_of_slide(
                tpl_s, bg_gray, raw_mask=mask_s, y_roi=y_roi
            )
            if score > best[1]:
                best = (loc, score, s, tpl_s)

        # Chamfer refine once around the best coarse hit
        coarse_xy, fused_score, best_scale, best_tpl = best
        refined_xy, _ = self._chamfer_refine(
            bg_gray, best_tpl, coarse_xy, search_radius=24
        )

        # Return x and fused score (keep your original external API)
        return refined_xy[0], fused_score


if __name__ == "__main__":
    solver = PuzzleSolver(
        gap_image_path="../../data_puzzle/2025-11-05/20251105_155959_image_puzzle_piece.png",
        bg_image_path="../../data_puzzle/2025-11-05/20251105_155959_image_puzzle_bg.png",
        output_image_path="../../data_puzzle/2025-11-05/20251105_155959_image_puzzle_result.png",
    )
    position = solver.discern()
    print(f"The position of the slide is: {position}")
