# -*- coding: utf-8 -*-
"""后台加载 PDF 的 QThread 工作对象，用于带进度条的加载。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from .pdf_loader import DEFAULT_DPI, get_pdf_toc

try:
    import fitz
except ImportError:
    fitz = None


class LoadPdfWorker(QObject):
    """在后台线程中加载单个 PDF 为灰度页列表，并发射进度。"""

    progress = pyqtSignal(int, int, str)  # current, total, label
    finished = pyqtSignal(object, object, str, bool)  # pages, toc, path, is_base
    error = pyqtSignal(str)

    def __init__(self, path: str, is_base: bool, dpi: int = DEFAULT_DPI):
        super().__init__()
        self._path = Path(path)
        self._is_base = is_base
        self._dpi = dpi

    def run(self) -> None:
        if fitz is None:
            self.error.emit("未安装 PyMuPDF (fitz)")
            return
        try:
            if not self._path.exists():
                self.error.emit(f"PDF 不存在: {self._path}")
                return
            doc = fitz.open(self._path)
            n = len(doc)
            zoom = self._dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            pages: List[np.ndarray] = []
            try:
                for page_num in range(n):
                    page = doc.load_page(page_num)
                    pix = page.get_pixmap(
                        matrix=matrix,
                        alpha=False,
                        colorspace=fitz.csGRAY,
                    )
                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                        pix.height, pix.width
                    )
                    pages.append(img)
                    label = "正在读取 PDF 页面... (%d/%d)" % (page_num + 1, n)
                    self.progress.emit(page_num + 1, n, label)
            finally:
                doc.close()
            toc: List[Tuple[int, str, int]] = get_pdf_toc(self._path) if self._is_base else []
            self.finished.emit(pages, toc, str(self._path), self._is_base)
        except Exception as e:
            self.error.emit(str(e))
