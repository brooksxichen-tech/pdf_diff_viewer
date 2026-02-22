# -*- coding: utf-8 -*-
"""主窗口：文件选择、页码切换、画布、拖放、页面映射、目录显隐、灵活视图、色彩模式、加载进度。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt, QThread
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpacerItem,
    QSplitter,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .canvas import FlexibleCompareView
from .diff_render import COLOR_SCHEMES, blend_diff
from .load_worker import LoadPdfWorker
from .page_mapping_dialog import PageMappingDialog
from .pdf_loader import get_pdf_toc
from .registration import LOW_OVERLAP_RATIO, align_compare_to_base
from .sidebar import PageOutlineSidebar


def _is_pdf(path: str) -> bool:
    return path.lower().endswith(".pdf")


class PathLineEdit(QLineEdit):
    """只读路径框：点击打开文件选择，长路径左侧省略，悬停手型，ToolTip 为完整路径。"""

    def __init__(self, on_click_callback: Optional[Callable[[], None]] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("未选择")
        self._full_path: str = ""
        self._on_click_callback = on_click_callback
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def setFilePath(self, path: str) -> None:
        self._full_path = path or ""
        self.setToolTip(self._full_path)
        self._refresh_elided()

    def _refresh_elided(self) -> None:
        if not self._full_path:
            self.setText("")
            self.setPlaceholderText("未选择")
            return
        w = self.width() - 16
        if w <= 0:
            self.setText(self._full_path)
            return
        elided = QFontMetrics(self.font()).elidedText(
            self._full_path, Qt.TextElideMode.ElideLeft, w
        )
        self.setText(elided)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_elided()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_click_callback:
            self._on_click_callback()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)


# 全局 QSS：极简无边框、浅灰降噪
GLOBAL_STYLESHEET = """
    QMainWindow, QWidget { background-color: #F8F9FA; }
    QFrame, QSplitter::handle { background-color: #F9F9F9; border: none; border-radius: 4px; }
    QLabel { color: #374151; }
    QPushButton {
        background-color: #F9F9F9;
        color: #374151;
        border: none;
        border-radius: 4px;
        padding: 6px 10px;
        min-height: 28px;
    }
    QPushButton:hover { background-color: #F0F0F0; }
    QPushButton:pressed { background-color: #E8E8E8; }
    QPushButton:disabled { background-color: #F5F5F5; color: #9CA3AF; }
    QPushButton:checked { background-color: #E8E8E8; }
    QLineEdit {
        background-color: #F9F9F9;
        color: #374151;
        border: none;
        border-radius: 4px;
        padding: 4px 8px;
        min-height: 20px;
    }
    QLineEdit:read-only { background-color: #F9F9F9; }
    QLineEdit:hover { background-color: #F0F0F0; }
    QProgressDialog { background-color: #F8F9FA; }
    QMessageBox { background-color: #FFFFFF; }
    #contentPanel { background-color: #FFFFFF; border: none; border-radius: 4px; }
    QMenu { background-color: #FFFFFF; border: none; padding: 4px; }
    QMenu::item:selected { background-color: #F0F0F0; }
"""


class DropCentralWidget(QWidget):
    """接受 PDF 拖放的中央容器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._on_drop_callback = None

    def set_drop_callback(self, callback) -> None:
        self._on_drop_callback = callback

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if any(_is_pdf(u) for u in urls):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            return
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        pdfs = sorted([u for u in urls if _is_pdf(u)])
        if not pdfs:
            return
        event.acceptProposedAction()
        if self._on_drop_callback:
            self._on_drop_callback(pdfs, event.position().toPoint())


class PdfDiffApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VisualAlign for PDF")
        self.setMinimumSize(900, 700)
        self.resize(1100, 800)

        self._base_pages: List[np.ndarray] = []
        self._compare_pages: List[np.ndarray] = []
        self._base_file_path: Optional[str] = None
        self._compare_file_path: Optional[str] = None
        self._current_page = 0
        self._last_diff_image: Optional[np.ndarray] = None
        self._last_overlap_ratio: float = 0.0
        self._color_scheme = "护眼白底"
        self._mapping_pairs: Optional[List[Tuple[int, int]]] = None
        self._toc: List[Tuple[int, str, int]] = []
        self._diff_rates: dict = {}
        self._show_base = False
        self._show_overlay = True
        self._show_compare = False
        self._load_thread: Optional[QThread] = None
        self._load_worker: Optional[LoadPdfWorker] = None
        self._progress_dialog: Optional[QProgressDialog] = None
        self._load_after_done: Optional[Callable[[], None]] = None

        # 目录容器（QFrame 包裹侧边栏，内含“目录”与列表）
        self._toc_frame = QFrame(self)
        toc_frame_layout = QVBoxLayout(self._toc_frame)
        toc_frame_layout.setContentsMargins(0, 0, 0, 0)
        self._sidebar = PageOutlineSidebar(self._toc_frame)
        self._sidebar.set_page_clicked_callback(self._on_sidebar_page_clicked)
        self._sidebar.setMinimumWidth(0)
        self._sidebar.setMaximumWidth(400)
        toc_frame_layout.addWidget(self._sidebar)

        self._btn_toc = QPushButton()
        self._btn_toc.setCheckable(True)
        self._btn_toc.setChecked(False)
        self._btn_toc.toggled.connect(self._on_toc_toggled)
        self._btn_toc.setMinimumHeight(32)

        self._btn_base = QPushButton()
        self._btn_base.setMinimumHeight(32)
        self._edit_base = PathLineEdit(on_click_callback=self._on_select_base, parent=self)
        self._btn_swap = QPushButton()
        self._btn_swap.clicked.connect(self._on_swap)
        self._btn_swap.setMinimumHeight(32)
        self._btn_compare = QPushButton()
        self._btn_compare.setMinimumHeight(32)
        self._edit_compare = PathLineEdit(on_click_callback=self._on_select_compare, parent=self)
        self._btn_mapping = QPushButton()
        self._btn_mapping.clicked.connect(self._on_page_mapping)
        self._btn_mapping.setMinimumHeight(32)

        self._menu_color = QMenu(self)
        for name in COLOR_SCHEMES.keys():
            act = self._menu_color.addAction(name)
            act.triggered.connect(lambda checked=False, n=name: self._on_color_scheme_changed(n))
        self._btn_color = QPushButton()
        self._btn_color.setMinimumHeight(32)
        self._btn_color.clicked.connect(self._on_show_color_menu)

        self._btn_view_overlay = QPushButton()
        self._btn_view_base = QPushButton()
        self._btn_view_compare = QPushButton()
        for b in (self._btn_view_overlay, self._btn_view_base, self._btn_view_compare):
            b.setCheckable(True)
            b.setMinimumHeight(32)
        self._view_btn_group = QButtonGroup(self)
        self._view_btn_group.addButton(self._btn_view_base)
        self._view_btn_group.addButton(self._btn_view_overlay)
        self._view_btn_group.addButton(self._btn_view_compare)
        self._view_btn_group.setExclusive(False)
        self._btn_view_overlay.setChecked(True)
        self._btn_view_base.toggled.connect(
            lambda v, b=self._btn_view_base: self._on_view_mode_toggled(b)
        )
        self._btn_view_overlay.toggled.connect(
            lambda v, b=self._btn_view_overlay: self._on_view_mode_toggled(b)
        )
        self._btn_view_compare.toggled.connect(
            lambda v, b=self._btn_view_compare: self._on_view_mode_toggled(b)
        )

        self._btn_prev = QPushButton()
        self._btn_prev.clicked.connect(self._on_prev_page)
        self._btn_prev.setMinimumHeight(32)
        self._btn_next = QPushButton()
        self._btn_next.clicked.connect(self._on_next_page)
        self._btn_next.setMinimumHeight(32)
        self._label_page = QLabel("第 0 / 0 页")
        self._label_overlap = QLabel("")

        right = DropCentralWidget(self)
        right.setObjectName("contentPanel")
        right.set_drop_callback(self._handle_drop)
        layout_right = QVBoxLayout(right)
        layout_right.setContentsMargins(4, 4, 4, 4)

        # 顶部控制区：极简单行弹性布局
        top_row = QHBoxLayout()
        top_row.setContentsMargins(10, 10, 10, 10)
        top_row.addWidget(self._btn_toc)
        top_row.addWidget(self._btn_base)
        top_row.addWidget(self._edit_base, 1)
        top_row.addWidget(self._btn_swap)
        top_row.addWidget(self._edit_compare, 1)
        top_row.addWidget(self._btn_compare)
        top_row.addSpacerItem(QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        top_row.addWidget(self._btn_view_overlay)
        top_row.addWidget(self._btn_view_base)
        top_row.addWidget(self._btn_view_compare)
        top_row.addWidget(self._btn_mapping)
        top_row.addWidget(self._btn_color)
        layout_right.addLayout(top_row)

        self._flex_view = FlexibleCompareView(self)
        layout_right.addWidget(self._flex_view, 1)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        bottom_row.addWidget(self._btn_prev)
        bottom_row.addWidget(self._btn_next)
        bottom_row.addWidget(self._label_page)
        bottom_row.addStretch()
        bottom_row.addWidget(self._label_overlap)
        layout_right.addLayout(bottom_row)

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.addWidget(self._toc_frame)
        self._main_splitter.addWidget(right)
        self._main_splitter.setStretchFactor(0, 0)
        self._main_splitter.setStretchFactor(1, 1)
        self._main_splitter.setSizes([0, 1100])

        self.setCentralWidget(self._main_splitter)
        self._toc_frame.setVisible(False)
        self._apply_icons()
        self._update_ui_state()

    def _apply_icons(self) -> None:
        try:
            import qtawesome as qta
            c = "#374151"
            self._btn_toc.setIcon(qta.icon("fa5s.bars", color=c))
            self._btn_toc.setToolTip("显示/隐藏目录")
            self._btn_base.setIcon(qta.icon("fa5s.folder-open", color=c))
            self._btn_base.setToolTip("选择基准文件 (PDF)")
            swap_icon = qta.icon("fa5s.exchange-alt", color=c)
            if swap_icon.isNull():
                swap_icon = qta.icon("fa5s.exchange", color=c)
            self._btn_swap.setIcon(swap_icon)
            self._btn_swap.setToolTip("基准与对比文件互换")
            self._btn_compare.setIcon(qta.icon("fa5s.folder-open", color=c))
            self._btn_compare.setToolTip("选择对比文件 (PDF)")
            self._btn_view_overlay.setIcon(qta.icon("fa5s.layer-group", color=c))
            self._btn_view_overlay.setToolTip("叠加差异图")
            self._btn_view_base.setIcon(qta.icon("fa5s.file-image", color=c))
            self._btn_view_base.setToolTip("显示基准文件原图")
            self._btn_view_compare.setIcon(qta.icon("fa5s.copy", color=c))
            self._btn_view_compare.setToolTip("显示对比文件原图")
            self._btn_mapping.setIcon(qta.icon("fa5s.list-ol", color=c))
            self._btn_mapping.setToolTip("页面映射设置")
            self._btn_color.setIcon(qta.icon("fa5s.palette", color=c))
            self._btn_color.setToolTip("色彩模式")
            self._btn_prev.setIcon(qta.icon("fa5s.chevron-left", color=c))
            self._btn_prev.setToolTip("上一页")
            self._btn_next.setIcon(qta.icon("fa5s.chevron-right", color=c))
            self._btn_next.setToolTip("下一页")
        except Exception:
            self._btn_toc.setToolTip("显示/隐藏目录")
            self._btn_base.setToolTip("选择基准文件 (PDF)")
            self._btn_swap.setToolTip("基准与对比文件互换")
            self._btn_compare.setToolTip("选择对比文件 (PDF)")
            self._btn_view_overlay.setToolTip("叠加差异图")
            self._btn_view_base.setToolTip("显示基准文件原图")
            self._btn_view_compare.setToolTip("显示对比文件原图")
            self._btn_mapping.setToolTip("页面映射设置")
            self._btn_color.setToolTip("色彩模式")
            self._btn_prev.setToolTip("上一页")
            self._btn_next.setToolTip("下一页")

    def _on_toc_toggled(self, checked: bool) -> None:
        self._toc_frame.setVisible(checked)
        if checked:
            self._main_splitter.setSizes([220, max(100, self._main_splitter.width() - 230)])

    def _on_show_color_menu(self) -> None:
        self._menu_color.exec(self._btn_color.mapToGlobal(self._btn_color.rect().bottomLeft()))

    def _on_color_scheme_changed(self, name: str) -> None:
        self._color_scheme = name
        self._refresh_diff()

    def _on_view_mode_toggled(self, toggled_button: Optional[QPushButton] = None) -> None:
        self._show_base = self._btn_view_base.isChecked()
        self._show_overlay = self._btn_view_overlay.isChecked()
        self._show_compare = self._btn_view_compare.isChecked()
        if not (self._show_base or self._show_overlay or self._show_compare):
            if toggled_button is not None:
                toggled_button.setChecked(True)
            self._show_base = self._btn_view_base.isChecked()
            self._show_overlay = self._btn_view_overlay.isChecked()
            self._show_compare = self._btn_view_compare.isChecked()
        self._flex_view.set_panes(self._show_base, self._show_overlay, self._show_compare)
        self._refresh_diff()

    def _get_display_order(self) -> List[Tuple[int, int]]:
        if self._mapping_pairs:
            return self._mapping_pairs
        n = min(len(self._base_pages), len(self._compare_pages))
        return [(i, i) for i in range(n)]

    def _rebuild_sidebar(self) -> None:
        order = self._get_display_order()
        if not order:
            self._sidebar.rebuild([], [], {}, 0)
            return
        self._sidebar.rebuild(
            self._toc,
            order,
            self._diff_rates,
            self._current_page,
        )

    def _on_sidebar_page_clicked(self, display_index: int) -> None:
        total = len(self._get_display_order())
        if 0 <= display_index < total:
            self._current_page = display_index
            self._refresh_diff()

    def _handle_drop(self, pdfs: List[str], pos) -> None:
        if len(pdfs) >= 2:
            self._load_base(pdfs[0], after_done=lambda: self._load_compare(pdfs[1]))
        else:
            msg = QMessageBox(self)
            msg.setWindowTitle("拖放文件")
            msg.setText("请选择目标位置")
            msg.setInformativeText(Path(pdfs[0]).name)
            b_base = msg.addButton("设为基准", QMessageBox.ButtonRole.ActionRole)
            b_compare = msg.addButton("设为对比", QMessageBox.ButtonRole.ActionRole)
            b_cancel = msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            btn = msg.clickedButton()
            if btn == b_base:
                self._load_base(pdfs[0])
            elif btn == b_compare:
                self._load_compare(pdfs[0])

    def _on_page_mapping(self) -> None:
        n_base = len(self._base_pages)
        n_compare = len(self._compare_pages)
        if n_base == 0 or n_compare == 0:
            QMessageBox.information(
                self, "页面映射", "请先加载基准文件和对比文件。"
            )
            return
        dlg = PageMappingDialog(n_base, n_compare, self)
        if dlg.exec():
            self._mapping_pairs = dlg.get_mapping_pairs()
            self._current_page = 0
            self._rebuild_sidebar()
            self._refresh_diff()
            self._update_ui_state()

    def _get_total_and_pair(self) -> Tuple[int, Optional[Tuple[int, int]]]:
        if self._mapping_pairs:
            total = len(self._mapping_pairs)
            if total == 0 or self._current_page >= total:
                return total, None
            return total, self._mapping_pairs[self._current_page]
        n_base = len(self._base_pages)
        n_compare = len(self._compare_pages)
        total = min(n_base, n_compare)
        if total == 0 or self._current_page >= total:
            return total, None
        return total, (self._current_page, self._current_page)

    def _update_ui_state(self) -> None:
        total, pair = self._get_total_and_pair()
        self._btn_prev.setEnabled(total > 0 and self._current_page > 0)
        self._btn_next.setEnabled(total > 0 and self._current_page < total - 1)
        self._label_page.setText(f"第 {self._current_page + 1} / {max(1, total)} 页")
        if self._last_overlap_ratio > 0 and self._last_overlap_ratio < LOW_OVERLAP_RATIO:
            self._label_overlap.setText("⚠ 重合度过低，可能非同一页面")
            self._label_overlap.setStyleSheet("color: #c00; font-weight: bold;")
        else:
            self._label_overlap.setText("")
            self._label_overlap.setStyleSheet("")

    def _on_swap(self) -> None:
        if not self._base_file_path or not self._compare_file_path:
            QMessageBox.information(
                self, "互换", "请先同时加载基准文件和对比文件后再互换。"
            )
            return
        self._base_file_path, self._compare_file_path = (
            self._compare_file_path, self._base_file_path
        )
        self._base_pages, self._compare_pages = self._compare_pages, self._base_pages
        try:
            self._toc = get_pdf_toc(self._base_file_path)
        except Exception:
            self._toc = []
        if self._mapping_pairs:
            self._mapping_pairs = [(c, b) for b, c in self._mapping_pairs]
        self._edit_base.setFilePath(self._base_file_path)
        self._edit_compare.setFilePath(self._compare_file_path)
        self._current_page = 0
        self._rebuild_sidebar()
        self._refresh_diff()
        self._update_ui_state()

    def _on_select_base(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择基准 PDF", os.path.expanduser("~"), "PDF 文件 (*.pdf)"
        )
        if path:
            self._load_base(path)

    def _on_select_compare(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择对比 PDF", os.path.expanduser("~"), "PDF 文件 (*.pdf)"
        )
        if path:
            self._load_compare(path)

    def _start_load(self, path: str, is_base: bool, after_done: Optional[Callable[[], None]] = None) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            return
        self._load_after_done = after_done
        label = "正在读取基准 PDF..." if is_base else "正在读取对比 PDF..."
        self._progress_dialog = QProgressDialog(label, None, 0, 0, self)
        self._progress_dialog.setWindowTitle("加载中")
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dialog.setValue(0)
        self._progress_dialog.show()
        QApplication.processEvents()

        self._load_worker = LoadPdfWorker(path, is_base)
        self._load_thread = QThread(self)
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.progress.connect(self._on_load_progress)
        self._load_worker.finished.connect(
            self._on_load_finished_base if is_base else self._on_load_finished_compare
        )
        self._load_worker.error.connect(self._on_load_error)
        self._load_thread.start()

    def _on_load_progress(self, current: int, total: int, label: str) -> None:
        dialog = self._progress_dialog
        if dialog is None:
            return
        try:
            dialog.setMaximum(total)
            dialog.setValue(current)
            dialog.setLabelText(label)
            QApplication.processEvents()
        except (AttributeError, RuntimeError):
            pass

    def _on_load_finished_base(self, pages: list, toc: list, path: str, is_base: bool) -> None:
        self._load_thread.quit()
        self._load_thread.wait()
        self._load_thread = None
        self._load_worker = None
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None
        self._base_pages = pages
        self._base_file_path = str(Path(path).resolve())
        self._edit_base.setFilePath(self._base_file_path)
        self._toc = toc
        self._mapping_pairs = None
        self._diff_rates = {}
        self._current_page = 0
        self._rebuild_sidebar()
        self._refresh_diff()
        after = self._load_after_done
        self._load_after_done = None
        if after is not None:
            after()

    def _on_load_finished_compare(self, pages: list, toc: list, path: str, is_base: bool) -> None:
        self._load_thread.quit()
        self._load_thread.wait()
        self._load_thread = None
        self._load_worker = None
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None
        self._compare_pages = pages
        self._compare_file_path = str(Path(path).resolve())
        self._edit_compare.setFilePath(self._compare_file_path)
        self._mapping_pairs = None
        self._diff_rates = {}
        self._current_page = 0
        self._rebuild_sidebar()
        self._refresh_diff()
        self._load_after_done = None

    def _on_load_error(self, message: str) -> None:
        if self._load_thread is not None:
            self._load_thread.quit()
            self._load_thread.wait()
        self._load_thread = None
        self._load_worker = None
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None
        self._load_after_done = None
        QMessageBox.critical(self, "加载失败", message)

    def _load_base(self, path: str, after_done: Optional[Callable[[], None]] = None) -> None:
        self._start_load(path, is_base=True, after_done=after_done)

    def _load_compare(self, path: str, after_done: Optional[Callable[[], None]] = None) -> None:
        self._start_load(path, is_base=False, after_done=after_done)

    def _on_prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._refresh_diff()

    def _on_next_page(self) -> None:
        total, _ = self._get_total_and_pair()
        if self._current_page < total - 1:
            self._current_page += 1
            self._refresh_diff()

    def _refresh_diff(self) -> None:
        total, pair = self._get_total_and_pair()
        empty = np.zeros((100, 100, 3), dtype=np.uint8)
        gray_empty = np.zeros((100, 100), dtype=np.uint8)
        if total == 0 or pair is None:
            self._flex_view.set_base_image(np.stack([gray_empty] * 3, axis=-1))
            self._flex_view.set_overlay_image(empty)
            self._flex_view.set_compare_image(np.stack([gray_empty] * 3, axis=-1))
            self._last_overlap_ratio = 0.0
            self._update_ui_state()
            return

        base_idx, compare_idx = pair
        base_img = self._base_pages[base_idx]
        compare_img = self._compare_pages[compare_idx]
        aligned, overlap_ratio = align_compare_to_base(base_img, compare_img)
        self._last_overlap_ratio = overlap_ratio
        self._diff_rates[self._current_page] = 1.0 - overlap_ratio
        self._sidebar.set_diff_rates(self._diff_rates)
        self._sidebar.set_current_index(self._current_page)

        base_3ch = np.stack([base_img, base_img, base_img], axis=-1)
        compare_3ch = np.stack([aligned, aligned, aligned], axis=-1)
        diff_rgb = blend_diff(
            base_img, aligned, color_scheme=self._color_scheme,
        )
        self._last_diff_image = diff_rgb
        self._flex_view.set_base_image(base_3ch)
        self._flex_view.set_overlay_image(diff_rgb)
        self._flex_view.set_compare_image(compare_3ch)
        self._update_ui_state()


def run_app() -> int:
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("VisualAlign for PDF")
    app.setStyleSheet(GLOBAL_STYLESHEET)
    win = PdfDiffApp()
    win.show()
    return app.exec()
