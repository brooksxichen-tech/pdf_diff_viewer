# -*- coding: utf-8 -*-
"""双通道差异可视化：多种色彩模式。"""

from __future__ import annotations

import numpy as np
from typing import Tuple

# 灰度 >= 此值视为空白
WHITE_THRESHOLD = 250

# 色彩模式：(背景, 重合, 仅基准, 仅对比) RGB
# 对比文件差异统一用红色系以突出显示；基准差异用蓝/青系。
COLOR_SCHEMES = {
    "护眼白底": (
        (255, 255, 255),   # 背景
        (0, 0, 0),         # 重合
        (0x99, 0xCC, 0xFF),   # 基准 → 浅蓝 #99CCFF
        (0xE6, 0x99, 0x99),   # 对比 → 浅红 #E69999
    ),
    "标准黑底": (
        (0, 0, 0),
        (255, 255, 255),
        (0, 255, 255),     # 基准 → 纯青
        (255, 0, 0),       # 对比 → 纯红
    ),
    "仿纸阅读": (
        (0xF5, 0xF1, 0xE6),   # 暖白 #F5F1E6
        (0x2C, 0x3E, 0x50),   # 深灰 #2C3E50
        (0x5E, 0x8B, 0x95),   # 基准 → 灰蓝 #5E8B95
        (0xC0, 0x6C, 0x5A),   # 对比 → 砖红 #C06C5A
    ),
    "柔和暗黑": (
        (0x1E, 0x1E, 0x1E),   # 深灰底 #1E1E1E
        (0xD4, 0xD4, 0xD4),   # 浅灰 #D4D4D4
        (0x56, 0x9C, 0xD6),   # 基准 → 柔和蓝 #569CD6
        (0xD1, 0x69, 0x69),   # 对比 → 柔和红 #D16969
    ),
}

DEFAULT_SCHEME = "护眼白底"


def grayscale_to_red_channel(gray: np.ndarray) -> np.ndarray:
    """灰度 -> RGB 红通道（黑底）。
    白(255)->黑，黑(0)->红。
    """
    gray = np.asarray(gray, dtype=np.float32)
    if gray.ndim > 2:
        gray = np.mean(gray, axis=2)
    r = 255 - np.clip(gray, 0, 255)
    r = r.astype(np.uint8)
    return np.stack([r, np.zeros_like(r), np.zeros_like(r)], axis=-1)


def grayscale_to_cyan_channel(gray: np.ndarray) -> np.ndarray:
    """灰度 -> RGB 青通道（黑底）。白->黑，黑->青。"""
    gray = np.asarray(gray, dtype=np.float32)
    if gray.ndim > 2:
        gray = np.mean(gray, axis=2)
    c = 255 - np.clip(gray, 0, 255)
    c = c.astype(np.uint8)
    return np.stack([np.zeros_like(c), c, c], axis=-1)


def _is_content_pixel(gray: np.ndarray, threshold: int) -> np.ndarray:
    """返回布尔数组，True 表示像素值 < threshold。"""
    if gray.ndim > 2:
        gray = np.mean(gray, axis=2)
    return (np.asarray(gray, dtype=np.float32) < threshold)


def blend_with_scheme(
    base_grayscale: np.ndarray,
    compare_grayscale_aligned: np.ndarray,
    scheme_name: str = DEFAULT_SCHEME,
    white_threshold: int = WHITE_THRESHOLD,
) -> np.ndarray:
    """按指定色彩模式混合基准与对比图。"""
    scheme = COLOR_SCHEMES.get(scheme_name, COLOR_SCHEMES[DEFAULT_SCHEME])
    bg, overlap_color, base_only_color, compare_only_color = scheme

    base = np.asarray(base_grayscale, dtype=np.uint8)
    compare = np.asarray(compare_grayscale_aligned, dtype=np.uint8)
    if base.ndim > 2:
        base = np.mean(base, axis=2).astype(np.uint8)
    if compare.ndim > 2:
        compare = np.mean(compare, axis=2).astype(np.uint8)

    base_content = _is_content_pixel(base, white_threshold)
    compare_content = _is_content_pixel(compare, white_threshold)
    overlap = base_content & compare_content
    only_base = base_content & (~compare_content)
    only_compare = (~base_content) & compare_content

    h, w = base.shape[:2]
    out = np.full((h, w, 3), bg, dtype=np.uint8)
    out[overlap] = overlap_color
    out[only_base] = base_only_color
    out[only_compare] = compare_only_color
    return out


def blend_diff(
    base_grayscale: np.ndarray,
    compare_grayscale_aligned: np.ndarray,
    color_scheme: str = DEFAULT_SCHEME,
    white_threshold: int = WHITE_THRESHOLD,
) -> np.ndarray:
    """根据色彩模式名称混合两幅灰度图。"""
    if isinstance(color_scheme, bool):
        color_scheme = "护眼白底" if color_scheme else "标准黑底"
    return blend_with_scheme(
        base_grayscale, compare_grayscale_aligned, color_scheme, white_threshold
    )
