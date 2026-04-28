from __future__ import annotations

import cv2
import numpy as np

from src.vision.puzzle.types import FloatMap, GrayImage, MaskImage


def compute_texture_variance(gray: GrayImage, window_size: int = 15) -> FloatMap:
    """
    Compute local texture variance to identify high-information regions.
    Low-texture areas (like grass) will have low variance.
    """
    gray_f = gray.astype(np.float32)
    mean = cv2.blur(gray_f, (window_size, window_size))
    sqr_mean = cv2.blur(gray_f**2, (window_size, window_size))
    variance = sqr_mean - (mean**2)
    variance = np.sqrt(np.maximum(variance, 0))
    return variance


def enhance_texture(gray: GrayImage) -> GrayImage:
    """Enhanced texture enhancement with better edge preservation."""
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    bilateral = cv2.bilateralFilter(enhanced, 9, 75, 75)

    gaussian = cv2.GaussianBlur(bilateral, (5, 5), 2.0)
    unsharp = cv2.addWeighted(bilateral, 1.8, gaussian, -0.8, 0)

    return np.clip(unsharp, 0, 255).astype(np.uint8)


def multi_scale_gradient(gray: GrayImage) -> GrayImage:
    """Multi-scale gradient with texture-aware weighting (NaN-safe)."""
    enhanced = enhance_texture(gray).astype(np.float32)

    texture_var = compute_texture_variance(enhanced, window_size=15).astype(np.float32)

    min_val, max_val, _, _ = cv2.minMaxLoc(texture_var)
    if max_val - min_val < 1e-6:
        texture_weight = np.ones_like(texture_var, dtype=np.float32)
    else:
        texture_weight = cv2.normalize(
            texture_var, None, 0.0, 1.0, cv2.NORM_MINMAX
        ).astype(np.float32)

    texture_weight = np.nan_to_num(texture_weight, nan=0.0, posinf=1.0, neginf=0.0)
    texture_weight = np.clip(texture_weight, 0.0, 1.0)

    gx1 = cv2.Sobel(enhanced, cv2.CV_32F, 1, 0, ksize=3)
    gy1 = cv2.Sobel(enhanced, cv2.CV_32F, 0, 1, ksize=3)
    mag1 = cv2.magnitude(gx1, gy1)

    blur2 = cv2.GaussianBlur(enhanced, (3, 3), 1.0)
    gx2 = cv2.Sobel(blur2, cv2.CV_32F, 1, 0, ksize=5)
    gy2 = cv2.Sobel(blur2, cv2.CV_32F, 0, 1, ksize=5)
    mag2 = cv2.magnitude(gx2, gy2)

    blur3 = cv2.GaussianBlur(enhanced, (5, 5), 2.0)
    gx3 = cv2.Sobel(blur3, cv2.CV_32F, 1, 0, ksize=7)
    gy3 = cv2.Sobel(blur3, cv2.CV_32F, 0, 1, ksize=7)
    mag3 = cv2.magnitude(gx3, gy3)

    combined = (0.5 * mag1 + 0.3 * mag2 + 0.2 * mag3).astype(np.float32)
    combined *= np.sqrt(texture_weight + 1e-6)

    combined = cv2.normalize(combined, None, 0.0, 255.0, cv2.NORM_MINMAX)
    combined = np.nan_to_num(combined, nan=0.0, posinf=255.0, neginf=0.0).astype(
        np.uint8
    )

    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(combined)


def adaptive_edge_mask(gray: GrayImage, mask: MaskImage | None = None) -> MaskImage:
    """Adaptive edge detection with texture filtering."""
    median = np.median(gray)
    sigma = 0.33
    lower = int(max(0, (1.0 - sigma) * median))
    upper = int(min(255, (1.0 + sigma) * median))

    lower = max(20, lower)
    upper = max(60, upper)

    edges = cv2.Canny(gray, lower, upper, L2gradient=True)

    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)

    edge_density = cv2.blur(edges.astype(np.float32), (15, 15))
    threshold = edge_density.max() * 0.1
    edges = np.where(edge_density > threshold, edges, 0).astype(np.uint8)

    if mask is not None:
        rm = (mask > 0).astype(np.uint8) * 255
        edges = cv2.bitwise_and(edges, rm)

    return edges


def compute_template_distinctiveness(tpl_gray: GrayImage) -> float:
    """
    Measure how distinctive the template is.
    Low distinctiveness = harder to match accurately.
    """
    edges = cv2.Canny(tpl_gray, 30, 100)
    edge_density = np.sum(edges > 0) / (tpl_gray.shape[0] * tpl_gray.shape[1])

    variance = np.std(tpl_gray) / 128.0

    hist = cv2.calcHist([tpl_gray], [0], None, [256], [0, 256])
    hist = hist / (hist.sum() + 1e-7)
    entropy = -np.sum(hist * np.log2(hist + 1e-7)) / 8.0

    distinctiveness = edge_density * 0.4 + variance * 0.3 + entropy * 0.3
    return float(distinctiveness)
