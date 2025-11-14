from pathlib import Path

import cv2
import numpy as np


class PuzzleSolver:
    def __init__(self, gap_image_path, bg_image_path, output_image_path):
        self.gap_image_path = gap_image_path
        self.bg_image_path = bg_image_path
        self.output_image_path = output_image_path

    def _imread_any(self, path):
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise FileNotFoundError(f"Cannot read image file: {path}")
        return img

    def _to_gray(self, img):
        if img.ndim == 2:
            return img
        if img.shape[2] == 4:
            return cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def _is_predominantly_white(self, img):
        """
        Detect if an image is predominantly white/bright.
        Returns (is_white, white_percentage)
        """
        if img.ndim == 3 and img.shape[2] >= 3:
            brightness = img[:, :, :3].mean(axis=2)
        else:
            brightness = img

        bright_pixels = (brightness > 240).sum()
        total_pixels = brightness.size
        bright_percentage = (bright_pixels / total_pixels) * 100

        return bright_percentage > 70, bright_percentage

    def _local_ncc_refine(self, bg_gray, tpl_gray, xy, radius: int = 3):
        """
        Final refinement in a small horizontal window using raw NCC
        (TM_CCOEFF_NORMED).

        Returns:
            (best_xy, best_score) where best_xy is (x, y).
            If no valid candidate is found, returns (xy, -1.0).
        """
        x0, y0 = int(xy[0]), int(xy[1])
        th, tw = tpl_gray.shape[:2]
        h_bg, w_bg = bg_gray.shape[:2]

        # Clamp vertical to valid region
        if y0 < 0:
            y0 = 0
        if y0 + th > h_bg:
            y0 = max(0, h_bg - th)

        best_x = x0
        best_score = -1.0

        for dx in range(-radius, radius + 1):
            x = x0 + dx
            if x < 0 or x + tw > w_bg:
                continue

            roi = bg_gray[y0 : y0 + th, x : x + tw]

            # roi and tpl_gray are same size here -> single NCC value
            res = cv2.matchTemplate(roi, tpl_gray, cv2.TM_CCOEFF_NORMED)
            score = float(res[0, 0])

            if score > best_score:
                best_score = score
                best_x = x

        if best_score < 0:
            # No valid candidate; signal "no change"
            return (x0, y0), -1.0

        print(
            f"[PuzzleSolver] NCC refine: from x={x0} to x={best_x}, "
            f"best_score={best_score:.4f}"
        )
        return (best_x, y0), best_score

    def _crop_by_mask(self, img):
        """
        Enhanced mask extraction that handles white puzzle pieces.
        """
        has_alpha = img.ndim == 3 and img.shape[2] == 4
        is_white, white_pct = self._is_predominantly_white(img)

        if has_alpha:
            alpha = img[:, :, 3]
            mask = (alpha > 5).astype(np.uint8) * 255
            print("[PuzzleSolver] Using alpha channel for masking")
        elif is_white:
            print(
                f"[PuzzleSolver] White puzzle piece detected ({white_pct:.1f}% bright)"
            )
            print("[PuzzleSolver] Using edge-based masking strategy")

            gray = self._to_gray(img) if img.ndim == 3 else img

            # Multi-threshold edge detection
            edges1 = cv2.Canny(gray, 10, 50, L2gradient=True)
            edges2 = cv2.Canny(gray, 30, 100, L2gradient=True)
            edges = cv2.bitwise_or(edges1, edges2)

            # Dilate for connectivity
            kernel = np.ones((5, 5), np.uint8)
            edges = cv2.dilate(edges, kernel, iterations=2)

            # Fill contours
            contours, _ = cv2.findContours(
                edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            mask = np.zeros(gray.shape, dtype=np.uint8)
            if contours:
                largest_contour = max(contours, key=cv2.contourArea)
                cv2.drawContours(mask, [largest_contour], -1, 255, -1)
                mask = cv2.morphologyEx(
                    mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2
                )
            else:
                mask = np.ones(gray.shape, dtype=np.uint8) * 255
                print("[PuzzleSolver] WARNING: No edges found, using full image")
        else:
            # Standard color-based masking
            bgr = (
                img
                if (img.ndim == 3 and img.shape[2] >= 3)
                else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            )
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            h, s, v = cv2.split(hsv)
            white = (v > 245) & (s < 20)
            mask = (~white).astype(np.uint8) * 255

        # Morphological cleanup
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1
        )
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1
        )

        # Find bounding box
        ys, xs = np.where(mask > 0)
        if len(xs) == 0 or len(ys) == 0:
            print("[PuzzleSolver] WARNING: Empty mask, using full image")
            return img, np.ones(img.shape[:2], dtype=np.uint8) * 255

        x0, x1 = xs.min(), xs.max()
        y0, y1 = ys.min(), ys.max()

        return img[y0 : y1 + 1, x0 : x1 + 1], mask[y0 : y1 + 1, x0 : x1 + 1]

    def _compute_texture_variance(self, gray, window_size=15):
        """
        Compute local texture variance to identify high-information regions.
        Low-texture areas (like grass) will have low variance.
        """
        mean = cv2.blur(gray.astype(np.float32), (window_size, window_size))
        sqr_mean = cv2.blur((gray.astype(np.float32) ** 2), (window_size, window_size))
        variance = sqr_mean - (mean**2)
        variance = np.sqrt(np.maximum(variance, 0))
        return variance

    def _center_from_mask(self, mask):
        """
        Compute geometric center of the puzzle shape from its binary mask.
        Returns (cx, cy) in template-local coordinates (float).
        """
        # Expect mask as 0/255 uint8, but accept any non-zero as foreground
        bin_mask = (mask > 0).astype(np.uint8)

        m = cv2.moments(bin_mask)
        if m["m00"] == 0:
            # Fallback to bounding-box center
            h, w = mask.shape[:2]
            return w / 2.0, h / 2.0

        cx = m["m10"] / m["m00"]
        cy = m["m01"] / m["m00"]
        return cx, cy

    def _enhance_texture(self, gray):
        """Enhanced texture enhancement with better edge preservation"""
        # Multi-stage enhancement
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # Bilateral filter preserves edges
        bilateral = cv2.bilateralFilter(enhanced, 9, 75, 75)

        # Strong unsharp mask
        gaussian = cv2.GaussianBlur(bilateral, (5, 5), 2.0)
        unsharp = cv2.addWeighted(bilateral, 1.8, gaussian, -0.8, 0)

        return np.clip(unsharp, 0, 255).astype(np.uint8)

    def _multi_scale_gradient(self, gray):
        """Multi-scale gradient with texture-aware weighting (NaN-safe)."""
        enhanced = self._enhance_texture(gray).astype(np.float32)

        # Compute texture variance map
        texture_var = self._compute_texture_variance(enhanced, window_size=15).astype(
            np.float32
        )

        # Safe normalize for texture_weight
        min_val, max_val, _, _ = cv2.minMaxLoc(texture_var)
        if max_val - min_val < 1e-6:
            # Degenerate: no variation => uniform weight
            texture_weight = np.ones_like(texture_var, dtype=np.float32)
        else:
            texture_weight = cv2.normalize(
                texture_var, None, 0.0, 1.0, cv2.NORM_MINMAX
            ).astype(np.float32)

        # Guard against NaNs / infs and clamp to [0, 1]
        texture_weight = np.nan_to_num(texture_weight, nan=0.0, posinf=1.0, neginf=0.0)
        texture_weight = np.clip(texture_weight, 0.0, 1.0)

        gradients = []

        # Fine details
        gx1 = cv2.Sobel(enhanced, cv2.CV_32F, 1, 0, ksize=3)
        gy1 = cv2.Sobel(enhanced, cv2.CV_32F, 0, 1, ksize=3)
        mag1 = cv2.magnitude(gx1, gy1)
        gradients.append(mag1)

        # Medium details
        blur2 = cv2.GaussianBlur(enhanced, (3, 3), 1.0)
        gx2 = cv2.Sobel(blur2, cv2.CV_32F, 1, 0, ksize=5)
        gy2 = cv2.Sobel(blur2, cv2.CV_32F, 0, 1, ksize=5)
        mag2 = cv2.magnitude(gx2, gy2)
        gradients.append(mag2)

        # Coarse structures
        blur3 = cv2.GaussianBlur(enhanced, (5, 5), 2.0)
        gx3 = cv2.Sobel(blur3, cv2.CV_32F, 1, 0, ksize=7)
        gy3 = cv2.Sobel(blur3, cv2.CV_32F, 0, 1, ksize=7)
        mag3 = cv2.magnitude(gx3, gy3)
        gradients.append(mag3)

        # Weighted combination in float
        combined = (
            0.5 * gradients[0] + 0.3 * gradients[1] + 0.2 * gradients[2]
        ).astype(np.float32)

        # Weight by texture variance (suppress low-texture regions)
        # Use sqrt, but keep it numerically safe
        combined *= np.sqrt(texture_weight + 1e-6)

        # Final normalization with NaN guard
        combined = cv2.normalize(combined, None, 0.0, 255.0, cv2.NORM_MINMAX)
        combined = np.nan_to_num(combined, nan=0.0, posinf=255.0, neginf=0.0).astype(
            np.uint8
        )

        # Local contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        combined = clahe.apply(combined)

        return combined

    def _adaptive_edge_mask(self, gray, mask=None):
        """Adaptive edge detection with texture filtering"""
        median = np.median(gray)
        sigma = 0.33
        lower = int(max(0, (1.0 - sigma) * median))
        upper = int(min(255, (1.0 + sigma) * median))

        lower = max(20, lower)
        upper = max(60, upper)

        edges = cv2.Canny(gray, lower, upper, L2gradient=True)

        # Dilate edges
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)

        # Compute edge density to filter low-information regions
        edge_density = cv2.blur(edges.astype(np.float32), (15, 15))

        # Suppress edges in low-density regions
        threshold = edge_density.max() * 0.1
        edges = np.where(edge_density > threshold, edges, 0).astype(np.uint8)

        if mask is not None:
            rm = (mask > 0).astype(np.uint8) * 255
            edges = cv2.bitwise_and(edges, rm)

        return edges

    def _compute_structural_complexity(self, gray, loc, template_shape):
        """
        Measure structural complexity at a given location.
        Returns higher values for regions with more features.
        """
        th, tw = template_shape
        y, x = int(loc[1]), int(loc[0])

        # Extract region
        y0 = max(0, y)
        y1 = min(gray.shape[0], y + th)
        x0 = max(0, x)
        x1 = min(gray.shape[1], x + tw)

        if y1 - y0 < th // 2 or x1 - x0 < tw // 2:
            return 0.0

        region = gray[y0:y1, x0:x1]

        # Compute multiple complexity measures

        # 1. Edge density
        edges = cv2.Canny(region, 30, 100, L2gradient=True)
        edge_density = np.sum(edges > 0) / (region.shape[0] * region.shape[1])

        # 2. Texture variance
        texture_var = np.std(region)

        # 3. Gradient magnitude
        gx = cv2.Sobel(region, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(region, cv2.CV_32F, 0, 1, ksize=3)
        grad_mag = np.mean(cv2.magnitude(gx, gy))

        # 4. Entropy (information content)
        hist = cv2.calcHist([region], [0], None, [256], [0, 256])
        hist = hist / (hist.sum() + 1e-7)
        entropy = -np.sum(hist * np.log2(hist + 1e-7))

        # Combine measures (normalized)
        complexity = (
            edge_density * 0.3
            + (texture_var / 128.0) * 0.25
            + (grad_mag / 255.0) * 0.25
            + (entropy / 8.0) * 0.2
        )

        return complexity

    def _filter_candidates_by_complexity(
        self,
        res_map,
        bg_gray,
        tpl_shape,
        top_k: int = 10,
        use_complexity: bool = True,
    ):
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

        h, w = res_map.shape
        candidates = []

        for idx in top_indices:
            y = idx // w
            x = idx % w
            score = float(res_map[y, x])

            # Always compute complexity so we can log it,
            # but how we use it depends on use_complexity.
            complexity = self._compute_structural_complexity(bg_gray, (x, y), tpl_shape)

            if use_complexity:
                # Original behavior: penalize very uniform regions,
                # reward structurally rich ones.
                if complexity < 0.15:
                    complexity_penalty = -0.15
                elif complexity < 0.25:
                    complexity_penalty = -0.05
                else:
                    complexity_penalty = min(0.10, complexity * 0.2)
                combined_score = score + complexity_penalty
            else:
                # LOW-TEXTURE MODE:
                # Don't penalize low complexity; give only a small bonus.
                # This lets smooth sky regions with good correlation win.
                complexity_bonus = min(0.05, max(0.0, complexity) * 0.1)
                combined_score = score + complexity_bonus

            candidates.append(
                {
                    "loc": (x, y),
                    "match_score": score,
                    "complexity": float(complexity),
                    "combined_score": float(combined_score),
                }
            )

        candidates.sort(key=lambda c: c["combined_score"], reverse=True)
        return candidates

    def _is_uniform_region(self, gray, loc, template_shape, threshold=0.02):
        """
        Detect uniform/low-detail regions (grass, solid colors).
        Returns True if region is too uniform to be a valid match.
        """
        th, tw = template_shape
        y, x = int(loc[1]), int(loc[0])

        y0 = max(0, y)
        y1 = min(gray.shape[0], y + th)
        x0 = max(0, x)
        x1 = min(gray.shape[1], x + tw)

        if y1 - y0 < th // 2 or x1 - x0 < tw // 2:
            return True

        region = gray[y0:y1, x0:x1]

        # Check edge density
        edges = cv2.Canny(region, 30, 100, L2gradient=True)
        edge_density = np.sum(edges > 0) / (region.shape[0] * region.shape[1])

        # Check standard deviation
        std_dev = np.std(region)

        # Uniform if low edges AND low variance
        is_uniform = (edge_density < threshold) and (std_dev < 15)

        return is_uniform

    def _match_maps_fused(self, bg_gray, tpl_gray, tpl_mask):
        """Enhanced matching with uniform region filtering"""
        m = None
        if tpl_mask is not None:
            m = tpl_mask
            if m.dtype != np.uint8:
                m = m.astype(np.uint8)
            if m.max() <= 1:
                m = (m > 0).astype(np.uint8) * 255

        # Three matching methods
        res_corr = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCORR_NORMED, mask=m)
        res_coef = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        res_sqdiff = cv2.matchTemplate(bg_gray, tpl_gray, cv2.TM_SQDIFF_NORMED)
        res_sqdiff = 1.0 - res_sqdiff

        # Normalize
        res_corr = cv2.normalize(res_corr, None, 0, 1, cv2.NORM_MINMAX)
        res_coef = cv2.normalize(res_coef, None, 0, 1, cv2.NORM_MINMAX)
        res_sqdiff = cv2.normalize(res_sqdiff, None, 0, 1, cv2.NORM_MINMAX)

        # Adaptive weighting
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

        # Get top candidates with complexity filtering (now returns 10 candidates)
        tpl_shape = tpl_gray.shape[:2]
        candidates = self._filter_candidates_by_complexity(
            fused, bg_gray, tpl_shape, top_k=10
        )

        # CRITICAL FIX: Filter out uniform regions
        valid_candidates = []
        for c in candidates:
            if not self._is_uniform_region(
                bg_gray, c["loc"], tpl_shape, threshold=0.02
            ):
                valid_candidates.append(c)
            else:
                print(f"[PuzzleSolver] REJECTED uniform region at {c['loc']}")

        # Fallback if all rejected
        if not valid_candidates:
            print("[PuzzleSolver] WARNING: All candidates rejected, using best anyway")
            valid_candidates = candidates[:1]

        best = valid_candidates[0]
        max_loc = best["loc"]
        max_val = best["match_score"]

        print("[PuzzleSolver] Top valid candidates:")
        for i, c in enumerate(valid_candidates[:3]):
            print(
                f"  {i + 1}. loc=({c['loc'][0]}, {c['loc'][1]}), "
                f"match={c['match_score']:.3f}, complexity={c['complexity']:.3f}, "
                f"combined={c['combined_score']:.3f}"
            )

        print(f"[PuzzleSolver] Selected: loc={max_loc}, match_score={max_val:.4f}")

        return fused, max_loc, float(max_val)

    def _compute_template_distinctiveness(self, tpl_gray):
        """
        Measure how distinctive the template is.
        Low distinctiveness = harder to match accurately.
        """
        # Edge density
        edges = cv2.Canny(tpl_gray, 30, 100)
        edge_density = np.sum(edges > 0) / (tpl_gray.shape[0] * tpl_gray.shape[1])

        # Variance
        variance = np.std(tpl_gray) / 128.0

        # Entropy
        hist = cv2.calcHist([tpl_gray], [0], None, [256], [0, 256])
        hist = hist / (hist.sum() + 1e-7)
        entropy = -np.sum(hist * np.log2(hist + 1e-7)) / 8.0

        distinctiveness = edge_density * 0.4 + variance * 0.3 + entropy * 0.3

        return distinctiveness

    def _local_maxima_validation(self, res_map, max_loc, threshold=0.95):
        """
        Validate peak significance.
        Returns ORIGINAL score with small confidence adjustment, not multiplied value.
        """
        h, w = res_map.shape
        x, y = max_loc
        max_val = res_map[y, x]

        window_size = 5
        x0 = max(0, x - window_size)
        x1 = min(w, x + window_size + 1)
        y0 = max(0, y - window_size)
        y1 = min(h, y + window_size + 1)

        window = res_map[y0:y1, x0:x1]

        mean_neighbors = np.mean(window)
        std_neighbors = np.std(window)

        is_significant = max_val > (mean_neighbors + 2 * std_neighbors)

        global_mean = np.mean(res_map)
        global_std = np.std(res_map)
        is_global_peak = max_val > (global_mean + 3 * global_std)

        # CRITICAL FIX: Only apply SMALL adjustments, never multiply
        # Original code was doing: confidence *= 1.15 which could exceed 1.0
        confidence = max_val

        if is_significant and is_global_peak:
            # Boost by small additive amount, not multiplicative
            confidence = min(1.0, confidence + 0.05)
        elif not is_significant:
            # Penalize slightly
            confidence = max(0.0, confidence - 0.05)

        return confidence

    def _subpixel_refine(self, res_map, max_loc, win=2):
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

        # Coordinates relative to integer peak
        ys, xs = np.mgrid[y0:y1, x0:x1].reshape(2, -1)
        xs = xs.astype(np.float32) - float(x)
        ys = ys.astype(np.float32) - float(y)
        Z = patch.reshape(-1)

        # Fit: a*x^2 + b*y^2 + c*x*y + d*x + e*y + f
        A = np.vstack([xs * xs, ys * ys, xs * ys, xs, ys, np.ones_like(xs)]).T
        try:
            coeff, _, _, _ = np.linalg.lstsq(A, Z, rcond=None)
        except np.linalg.LinAlgError:
            return float(x), float(y)

        a, b, c, d, e, f = coeff

        # Stationary point of quadratic
        denom = 4 * a * b - c * c
        if abs(denom) < 1e-6:
            return float(x), float(y)

        dx = (c * e - 2 * b * d) / denom
        dy = (c * d - 2 * a * e) / denom

        # Limit refinement to half a pixel in each direction
        dx = float(np.clip(dx, -0.5, 0.5))
        dy = float(np.clip(dy, -0.5, 0.5))

        return x + dx, y + dy

    def _chamfer_refine(self, bg_gray, tpl_gray, coarse_xy, search_radius=5):
        """Chamfer refinement with minimal radius"""
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
        tpl_edges = (tpl_edges > 0).astype(np.float32)

        res = cv2.matchTemplate(dt, tpl_edges, cv2.TM_SQDIFF)
        min_val, _, min_loc, _ = cv2.minMaxLoc(res)

        refined = (x0 + min_loc[0], y0 + min_loc[1])

        dx = abs(refined[0] - coarse_xy[0])
        dy = abs(refined[1] - coarse_xy[1])

        if dx <= 3 and dy <= 3:
            return refined, float(min_val)
        else:
            return coarse_xy, float(min_val)

    def _draw_match_visualization(
        self, bg_gray, tl, tw, th, score, tpl_center_local=None
    ):
        """
        Visualization with confidence color and true jigsaw center.

        tl: (x, y) top-left of template in background (float).
        tpl_center_local: (cx, cy) center in template-local coordinates (float),
                        computed from the mask; if None, falls back to bbox center.
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

        # Use geometric center of the shape if provided
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

    def find_position_of_slide(self, tpl_gray, bg_gray, raw_mask=None, y_roi=None):
        """
        Find position with gradient+chamfer fusion and complexity-based validation.

        For high-texture templates (trees, horizon), use the full
        gradient+complexity pipeline.

        For low-texture templates (sky pieces, very smooth regions),
        relax complexity/uniform filtering and trust correlation+chamfer
        more, otherwise the true sky location gets unfairly penalized.
        """
        # 0) Distinctiveness report (unchanged)
        distinctiveness = self._compute_template_distinctiveness(tpl_gray)
        print(f"[PuzzleSolver] Template distinctiveness: {distinctiveness:.3f}")

        low_texture_mode = distinctiveness < 0.35
        if low_texture_mode:
            print("[PuzzleSolver] LOW-TEXTURE MODE (sky / smooth piece detected)")
        else:
            print("[PuzzleSolver] HIGH-TEXTURE MODE")

        # 1) Build gradient-based maps
        tpl_grad = self._multi_scale_gradient(tpl_gray)
        bg_grad = self._multi_scale_gradient(bg_gray)

        # Edge-derived mask from template content and optional raw mask
        edge_mask = self._adaptive_edge_mask(tpl_gray, raw_mask)

        # 2) Background edge distance transform (for chamfer)
        bg_edges_full = self._adaptive_edge_mask(bg_gray, None)
        inv_full = (bg_edges_full == 0).astype(np.uint8) * 255
        dt_full = cv2.distanceTransform(inv_full, cv2.DIST_L2, 5).astype(np.float32)

        # Template edges as float "stamp"
        tpl_edges = self._adaptive_edge_mask(tpl_gray, None)
        tpl_edges_f = (tpl_edges > 0).astype(np.float32)

        # 3) Fused correlation map on gradients
        if y_roi is not None:
            y0, y1 = y_roi
            fused_map, _, _ = self._match_maps_fused(
                bg_grad[y0:y1, :], tpl_grad, edge_mask
            )
            dt_roi = dt_full[y0:y1, :]
            res_dt = cv2.matchTemplate(dt_roi, tpl_edges_f, cv2.TM_SQDIFF)
            res_dt = cv2.normalize(res_dt, None, 0, 1, cv2.NORM_MINMAX)
            chamfer_sim = 1.0 - res_dt
            bg_gray_for_rank = bg_gray[y0:y1, :]
        else:
            fused_map, _, _ = self._match_maps_fused(bg_grad, tpl_grad, edge_mask)
            res_dt = cv2.matchTemplate(dt_full, tpl_edges_f, cv2.TM_SQDIFF)
            res_dt = cv2.normalize(res_dt, None, 0, 1, cv2.NORM_MINMAX)
            chamfer_sim = 1.0 - res_dt
            bg_gray_for_rank = bg_gray

        # 4) Combine maps
        if low_texture_mode:
            # Sky pieces: rely more on chamfer (shape alignment) and
            # a little less on pure gradient, which is weak in flat regions.
            w_grad, w_chamfer = 0.5, 0.5
        else:
            # Original tuning for richer structure
            w_grad, w_chamfer = 0.65, 0.35

        combined_map = w_grad * fused_map + w_chamfer * chamfer_sim
        combined_map = cv2.normalize(combined_map, None, 0, 1, cv2.NORM_MINMAX)

        # 5) Candidate generation + complexity gating
        th, tw = tpl_gray.shape[:2]
        candidates = self._filter_candidates_by_complexity(
            combined_map,
            bg_gray_for_rank,
            (th, tw),
            top_k=10,
            use_complexity=not low_texture_mode,
        )

        # 6) Remove uniform/flat areas aggressively ONLY in high-texture mode
        valid = []
        for c in candidates:
            if not low_texture_mode:
                # Original behavior: reject very uniform regions
                if self._is_uniform_region(
                    bg_gray_for_rank, c["loc"], (th, tw), threshold=0.02
                ):
                    print(f"[PuzzleSolver] REJECTED uniform region at {c['loc']}")
                    continue

            # Blend correlation + chamfer at candidate for a final score
            y, x = int(c["loc"][1]), int(c["loc"][0])
            s_grad = float(fused_map[y, x])
            s_cham = float(chamfer_sim[y, x])

            # In low-texture mode, increase chamfer weight slightly
            if low_texture_mode:
                final_score = 0.5 * s_grad + 0.5 * s_cham
            else:
                final_score = 0.6 * s_grad + 0.4 * s_cham

            c["final_score"] = final_score
            valid.append(c)

        if not valid:
            print(
                "[PuzzleSolver] WARNING: All candidates rejected, using best-by-map anyway"
            )
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(combined_map)
            best_loc = (max_loc[0], max_loc[1])
            best_score = float(max_val)
        else:
            valid.sort(key=lambda z: z["final_score"], reverse=True)
            best = valid[0]
            best_loc = best["loc"]
            best_score = float(best["final_score"])

        # 7) Sub-pixel refinement on the combined response
        loc_sub = self._subpixel_refine(
            combined_map, (int(best_loc[0]), int(best_loc[1]))
        )

        # Map back from ROI, if any
        if y_roi is not None:
            y0, _ = y_roi
            tl = (loc_sub[0], loc_sub[1] + y0)
        else:
            tl = loc_sub

        # 8) Final chamfer-based geometric refine in a small window
        refined_xy, chamfer_dist = self._chamfer_refine(
            bg_gray,
            tpl_gray,
            (int(round(tl[0])), int(round(tl[1]))),
            search_radius=5,
        )

        # 9) Local NCC refinement in a +/- 3 px horizontal window
        refined_xy_ncc, ncc_score = self._local_ncc_refine(
            bg_gray,
            tpl_gray,
            refined_xy,
            radius=3,
        )

        if ncc_score > 0:
            final_xy = refined_xy_ncc
        else:
            # NCC could not improve / no valid candidate; keep chamfer result
            final_xy = refined_xy

        final_x, final_y = int(round(final_xy[0])), int(round(final_xy[1]))
        print(
            f"[PuzzleSolver] Final refined position: ({final_x}, {final_y}), "
            f"fused_score={best_score:.4f}, ncc_score={ncc_score:.4f}"
        )

        # 10) Visualization and return (same signature as before)
        vis = self._draw_match_visualization(
            self._multi_scale_gradient(bg_gray),
            (float(final_x), float(final_y)),
            tw,
            th,
            best_score,
            tpl_center_local=getattr(self, "tpl_center_local", None),
        )
        Path(self.output_image_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(self.output_image_path, vis)

        return (final_x, final_y), float(best_score)

    def discern_xy(self, y_roi=None, scales=(0.95, 1.0, 1.05)):
        """Main solver with complexity filtering"""
        gap_raw = self._imread_any(self.gap_image_path)
        bg_raw = self._imread_any(self.bg_image_path)

        gap_cropped, gap_mask = self._crop_by_mask(gap_raw)
        tpl_gray = self._to_gray(gap_cropped)
        bg_gray = self._to_gray(bg_raw)

        # NEW: compute center of the jigsaw shape in template-local coords
        self.tpl_center_local = self._center_from_mask(gap_mask)

        best = (None, -1.0, None, None)

        for s in scales:
            if s != 1.0:
                th, tw = tpl_gray.shape[:2]
                new_size = (max(1, int(tw * s)), max(1, int(th * s)))
                tpl_s = cv2.resize(tpl_gray, new_size, interpolation=cv2.INTER_CUBIC)
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

            print(f"[PuzzleSolver] Scale {s:.2f}: score={score:.4f}, loc={loc}")

            if score > best[1]:
                best = (loc, score, s, tpl_s)

        coarse_xy, fused_score, best_scale, best_tpl = best

        print(f"[PuzzleSolver] Best scale: {best_scale:.2f}, score: {fused_score:.4f}")

        refined_xy, chamfer_dist = self._chamfer_refine(
            bg_gray,
            best_tpl,
            (int(round(coarse_xy[0])), int(round(coarse_xy[1]))),
            search_radius=5,
        )

        th, tw = best_tpl.shape[:2]

        return (
            int(round(refined_xy[0])),
            int(round(refined_xy[1])),
            float(fused_score),
            float(best_scale),
            (int(tw), int(th)),
        )
