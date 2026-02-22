# -*- coding: utf-8 -*-
"""图像自动配准：ORB 特征 + RANSAC，可选 ECC 精化。"""

from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np

# 非白色阈值：灰度 >= 此值视为空白，忽略边缘对齐
WHITE_THRESHOLD = 250

# 重合度过低时判定为“可能非同一页”的阈值（非白色像素重叠比例）
LOW_OVERLAP_RATIO = 0.15


def _mask_non_white(gray: np.ndarray, threshold: int = WHITE_THRESHOLD) -> np.ndarray:
    """非白色区域二值掩码：0=白/忽略，255=内容。"""
    return np.where(gray < threshold, 255, 0).astype(np.uint8)


def _crop_margin_to_content(
    img: np.ndarray,
    margin_ratio: float = 0.05,
    white_threshold: int = WHITE_THRESHOLD,
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """
    裁掉四周空白，保留内容区域，减少边缘对齐干扰。
    返回 (裁剪后图像, (x, y, w, h) 在原图中的 ROI)。
    """
    h, w = img.shape[:2]
    mask = (img < white_threshold).astype(np.uint8)
    if mask.ndim > 2:
        mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    xs, ys = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        return img, (0, 0, w, h)
    x_min, x_max = int(ys.min()), int(ys.max())
    y_min, y_max = int(xs.min()), int(xs.max())
    # 留一点边
    margin_w = max(1, int((x_max - x_min) * margin_ratio))
    margin_h = max(1, int((y_max - y_min) * margin_ratio))
    x_min = max(0, x_min - margin_w)
    x_max = min(w, x_max + margin_w)
    y_min = max(0, y_min - margin_h)
    y_max = min(h, y_max + margin_h)
    roi = (x_min, y_min, x_max - x_min, y_max - y_min)
    return img[y_min:y_max, x_min:x_max], roi


def estimate_transform_orb_ransac(
    base: np.ndarray,
    compare: np.ndarray,
    max_features: int = 5000,
    ransac_threshold: float = 5.0,
) -> Tuple[np.ndarray, float]:
    """
    使用 ORB 特征 + RANSAC 估计从 compare 到 base 的仿射/透视变换。
    以非白色区域为主（在掩码上检测或仅用内容 ROI）。

    Returns:
        (H, 2, 3) 仿射矩阵（2x3），或 (3, 3) 单应性矩阵；若失败返回 identity。
        overlap_ratio: 对齐后非白色像素重合比例（相对基准页非白像素），用于低重合度提示。
    """
    if base.ndim > 2:
        base = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    if compare.ndim > 2:
        compare = cv2.cvtColor(compare, cv2.COLOR_BGR2GRAY)

    # 尺寸不一致时，将 compare 缩放到 base 的尺寸再配准
    h_b, w_b = base.shape[:2]
    h_c, w_c = compare.shape[:2]
    if (h_c, w_c) != (h_b, w_b):
        compare_resized = cv2.resize(compare, (w_b, h_b), interpolation=cv2.INTER_AREA)
    else:
        compare_resized = compare

    # 可选：在内容区域做特征检测，减少边缘干扰（用整图也可）
    base_for_kp = base
    compare_for_kp = compare_resized

    orb = cv2.ORB_create(nfeatures=max_features)
    kp1, des1 = orb.detectAndCompute(base_for_kp, None)
    kp2, des2 = orb.detectAndCompute(compare_for_kp, None)

    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        # 特征不足，尝试 ECC
        M, overlap_ratio = _estimate_transform_ecc(base, compare_resized)
        return M, overlap_ratio

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)
    good = []
    for m_n in matches:
        if len(m_n) != 2:
            continue
        m, n = m_n
        if m.distance < 0.75 * n.distance:
            good.append(m)

    if len(good) < 4:
        M, overlap_ratio = _estimate_transform_ecc(base, compare_resized)
        return M, overlap_ratio

    src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    # 仿射变换（平移+旋转+缩放），比单应性更稳定 for 平面扫描件
    M, inliers = cv2.estimateAffinePartial2D(
        dst_pts, src_pts, method=cv2.RANSAC, ransacReprojThreshold=ransac_threshold
    )
    if M is None:
        M, overlap_ratio = _estimate_transform_ecc(base, compare_resized)
        return M, overlap_ratio

    # 将 compare 按 M 变换到 base 坐标系，再计算重叠度
    compare_warped = cv2.warpAffine(
        compare_resized, M, (w_b, h_b), borderMode=cv2.BORDER_CONSTANT, borderValue=255
    )
    overlap_ratio = _compute_overlap_ratio(base, compare_warped)

    # 返回 2x3 仿射矩阵（应用时对 compare 做 warpAffine）
    return M, overlap_ratio


def _estimate_transform_ecc(
    base: np.ndarray,
    compare: np.ndarray,
    number_of_iterations: int = 5000,
) -> Tuple[np.ndarray, float]:
    """ECC 光流法估计 2x3 仿射变换。"""
    if base.ndim > 2:
        base = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    if compare.ndim > 2:
        compare = cv2.cvtColor(compare, cv2.COLOR_BGR2GRAY)
    h, w = base.shape[:2]
    if compare.shape[:2] != (h, w):
        compare = cv2.resize(compare, (w, h), interpolation=cv2.INTER_AREA)

    M = np.eye(2, 3, dtype=np.float32)
    try:
        criteria = (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            number_of_iterations,
            1e-6,
        )
        _ = cv2.findTransformECC(
            cv2.GaussianBlur(base, (5, 5), 0),
            cv2.GaussianBlur(compare, (5, 5), 0),
            M,
            cv2.MOTION_EUCLIDEAN,
            criteria,
        )
    except cv2.error:
        M = np.eye(2, 3, dtype=np.float32)

    compare_warped = cv2.warpAffine(
        compare, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=255
    )
    overlap_ratio = _compute_overlap_ratio(base, compare_warped)
    return M, overlap_ratio


def _compute_overlap_ratio(base: np.ndarray, compare_warped: np.ndarray) -> float:
    """
    计算基准页非白色像素中，与对比页对齐后也非白色的比例。
    忽略边缘空白，以内容区域为主。
    """
    mask_b = _mask_non_white(base)
    mask_c = _mask_non_white(compare_warped)
    non_white_b = (mask_b > 0).sum()
    if non_white_b == 0:
        return 0.0
    overlap = ((mask_b > 0) & (mask_c > 0)).sum()
    return float(overlap) / float(non_white_b)


def align_compare_to_base(
    base: np.ndarray,
    compare: np.ndarray,
    use_ecc_fallback: bool = True,
) -> Tuple[np.ndarray, float]:
    """
    将对 compare 做几何变换，使其与 base 对齐。
    返回 (对齐后的 compare 图像, overlap_ratio)。
    """
    if base.ndim > 2:
        base = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    if compare.ndim > 2:
        compare = cv2.cvtColor(compare, cv2.COLOR_BGR2GRAY)
    h_b, w_b = base.shape[:2]
    h_c, w_c = compare.shape[:2]
    if (h_c, w_c) != (h_b, w_b):
        compare = cv2.resize(compare, (w_b, h_b), interpolation=cv2.INTER_AREA)

    M, overlap_ratio = estimate_transform_orb_ransac(base, compare)
    aligned = cv2.warpAffine(
        compare, M, (w_b, h_b), borderMode=cv2.BORDER_CONSTANT, borderValue=255
    )
    return aligned, overlap_ratio
