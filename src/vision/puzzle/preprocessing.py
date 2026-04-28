from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.vision.puzzle.types import GrayImage, ImageArray, MaskImage, PointF, YRoi


def ensure_output_dir(output_image_path: str) -> None:
    Path(output_image_path).parent.mkdir(parents=True, exist_ok=True)


def imread_any(path: str) -> ImageArray:
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Cannot read image file: {path}")
    return img


def to_gray(img: ImageArray) -> GrayImage:
    if img.ndim == 2:
        return img
    if img.shape[2] == 4:
        return cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def compute_processing_scale(
    image_shape: tuple[int, int], max_processing_side: int = 420
) -> float:
    h, w = image_shape[:2]
    max_side = max(int(h), int(w))
    if max_side <= max_processing_side:
        return 1.0
    return float(max_processing_side) / float(max_side)


def resize_gray(gray: GrayImage, scale: float) -> GrayImage:
    if abs(scale - 1.0) < 1e-6:
        return gray

    h, w = gray.shape[:2]
    new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(gray, new_size, interpolation=interpolation)


def resize_mask(mask: MaskImage, scale: float) -> MaskImage:
    if abs(scale - 1.0) < 1e-6:
        return mask

    h, w = mask.shape[:2]
    new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    return cv2.resize(mask, new_size, interpolation=cv2.INTER_NEAREST)


def preprocess_for_matching(gray: GrayImage) -> GrayImage:
    """
    Normalize grayscale inputs for matching.

    The pipeline intentionally stays lightweight because this runs per scale:
    mild denoising, local contrast equalization, then a small unsharp pass.
    """
    denoised = cv2.fastNlMeansDenoising(gray, None, h=5, templateWindowSize=7, searchWindowSize=21)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    equalized = clahe.apply(denoised)

    blur = cv2.GaussianBlur(equalized, (0, 0), 1.2)
    sharpened = cv2.addWeighted(equalized, 1.2, blur, -0.2, 0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def build_match_mask(mask: MaskImage | None, erode_iterations: int = 1) -> MaskImage | None:
    if mask is None:
        return None

    match_mask = mask.astype(np.uint8)
    if match_mask.max() <= 1:
        match_mask = (match_mask > 0).astype(np.uint8) * 255

    match_mask = cv2.morphologyEx(
        match_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1
    )
    if erode_iterations > 0 and min(match_mask.shape[:2]) >= 12:
        match_mask = cv2.erode(
            match_mask, np.ones((3, 3), np.uint8), iterations=erode_iterations
        )

    if not np.any(match_mask > 0):
        return None
    return match_mask


def scale_y_roi(y_roi: YRoi, scale: float) -> YRoi:
    if y_roi is None or abs(scale - 1.0) < 1e-6:
        return y_roi

    y0, y1 = y_roi
    return int(round(y0 * scale)), int(round(y1 * scale))


def is_predominantly_white(
    img: ImageArray,
    brightness_threshold: int,
    white_percent_threshold: float,
) -> tuple[bool, float]:
    if img.ndim == 3 and img.shape[2] >= 3:
        brightness = img[:, :, :3].mean(axis=2)
    else:
        brightness = img

    bright_pixels = (brightness > brightness_threshold).sum()
    total_pixels = brightness.size
    bright_percentage = (bright_pixels / total_pixels) * 100
    return bright_percentage > white_percent_threshold, float(bright_percentage)


def crop_by_mask(
    img: ImageArray,
    white_brightness_threshold: int,
    white_percent_threshold: float,
) -> tuple[ImageArray, MaskImage]:
    """
    Enhanced mask extraction that handles white puzzle pieces.
    """
    has_alpha = img.ndim == 3 and img.shape[2] == 4
    is_white, _ = is_predominantly_white(
        img, white_brightness_threshold, white_percent_threshold
    )

    if has_alpha:
        alpha = img[:, :, 3]
        mask = (alpha > 5).astype(np.uint8) * 255
    elif is_white:
        gray = to_gray(img) if img.ndim == 3 else img

        edges1 = cv2.Canny(gray, 10, 50, L2gradient=True)
        edges2 = cv2.Canny(gray, 30, 100, L2gradient=True)
        edges = cv2.bitwise_or(edges1, edges2)

        kernel = np.ones((5, 5), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=2)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        mask = np.zeros(gray.shape, dtype=np.uint8)

        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            cv2.drawContours(mask, [largest_contour], -1, 255, -1)
            mask = cv2.morphologyEx(
                mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2
            )
        else:
            mask = np.ones(gray.shape, dtype=np.uint8) * 255
    else:
        bgr = (
            img
            if (img.ndim == 3 and img.shape[2] >= 3)
            else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        )
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        _h, s, v = cv2.split(hsv)
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
        return img, np.ones(img.shape[:2], dtype=np.uint8) * 255

    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    return img[y0 : y1 + 1, x0 : x1 + 1], mask[y0 : y1 + 1, x0 : x1 + 1]


def center_from_mask(mask: MaskImage) -> PointF:
    """
    Compute geometric center of the puzzle shape from its binary mask.
    Returns (cx, cy) in template-local coordinates (float).
    """
    bin_mask = (mask > 0).astype(np.uint8)

    m = cv2.moments(bin_mask)
    if m["m00"] == 0:
        h, w = mask.shape[:2]
        return w / 2.0, h / 2.0

    cx = m["m10"] / m["m00"]
    cy = m["m01"] / m["m00"]
    return float(cx), float(cy)


def scale_template_and_mask(
    tpl_gray: GrayImage, gap_mask: MaskImage, scale: float
) -> tuple[GrayImage, MaskImage]:
    if scale == 1.0:
        return tpl_gray, gap_mask

    th, tw = tpl_gray.shape[:2]
    new_size = (max(1, int(tw * scale)), max(1, int(th * scale)))
    tpl_s = cv2.resize(tpl_gray, new_size, interpolation=cv2.INTER_CUBIC)
    mask_s = cv2.resize(gap_mask, new_size, interpolation=cv2.INTER_NEAREST)
    return tpl_s, mask_s
