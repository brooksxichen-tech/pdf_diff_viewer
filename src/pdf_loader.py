# -*- coding: utf-8 -*-
"""PDF 转高分辨率灰度图像与书签 (PyMuPDF)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import fitz  # PyMuPDF
import numpy as np

# 默认渲染 DPI，满足至少 300 DPI
DEFAULT_DPI = 300


def load_pdf_pages_as_grayscale(
    pdf_path: str | Path,
    dpi: int = DEFAULT_DPI,
) -> List[np.ndarray]:
    """
    将 PDF 每一页渲染为高分辨率灰度图像 (NumPy uint8, 0-255)。

    Args:
        pdf_path: PDF 文件路径
        dpi: 渲染分辨率，默认 300

    Returns:
        每页对应一个灰度图 (H, W)，白色为 255，黑色为 0。
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0  # PyMuPDF 默认 72 DPI
    matrix = fitz.Matrix(zoom, zoom)
    pages: List[np.ndarray] = []

    try:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(
                matrix=matrix,
                alpha=False,
                colorspace=fitz.csGRAY,
            )
            # (width, height) -> (height, width), 0-255
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width
            )
            pages.append(img)
    finally:
        doc.close()

    return pages


def load_pdf_pages_as_rgb(
    pdf_path: str | Path,
    dpi: int = DEFAULT_DPI,
) -> List[np.ndarray]:
    """
    将 PDF 每一页渲染为 RGB 图像 (H, W, 3) uint8，用于红章过滤等预处理。
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")
    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pages: List[np.ndarray] = []
    try:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(
                matrix=matrix,
                alpha=False,
                colorspace=fitz.csRGB,
            )
            # pix.samples: RGB 交错 (R,G,B,R,G,B,...)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, 3
            )
            pages.append(img.copy())
    finally:
        doc.close()
    return pages


def get_pdf_toc(pdf_path: str | Path) -> List[Tuple[int, str, int]]:
    """
    读取 PDF 书签/目录 (TOC/Outlines)。

    Returns:
        [(level, title, page_0based), ...]
        level: 层级，从 1 开始
        title: 标题字符串
        page_0based: 页码，0 起算（与 load_page 一致）
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return []
    doc = fitz.open(pdf_path)
    try:
        raw = doc.get_toc()
        out: List[Tuple[int, str, int]] = []
        for item in raw:
            if len(item) < 3:
                continue
            level = int(item[0])
            title = str(item[1]).strip()
            # PDF 书签页码通常为 1-based
            p = int(item[2])
            page_0based = max(0, p - 1) if p >= 1 else 0
            out.append((level, title, page_0based))
        return out
    finally:
        doc.close()
