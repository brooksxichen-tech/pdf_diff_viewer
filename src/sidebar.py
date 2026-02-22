# -*- coding: utf-8 -*-
"""侧边栏目录与差异率展示。"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# 差异率超过此值用红色标识
DIFF_RATE_ALERT_THRESHOLD = 0.005  # 0.5%

# 用于存储 display_index 的 DataRole
ROLE_DISPLAY_INDEX = Qt.ItemDataRole.UserRole


def _format_rate(rate: Optional[float]) -> str:
    if rate is None:
        return "—"
    return f"{rate * 100:.1f}%"


class PageOutlineSidebar(QWidget):
    """
    左侧可折叠侧边栏：QTreeWidget（有 TOC）或 QListWidget（无 TOC），
    第二列显示差异率；点击项跳转对应页。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(180)
        self.setMaximumWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel("目录")
        self._title.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(self._title)
        self._stack = QWidget()
        self._stack_layout = QVBoxLayout(self._stack)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
        self._tree: Optional[QTreeWidget] = None
        self._list: Optional[QListWidget] = None
        self._on_page_clicked: Optional[Callable[[int], None]] = None
        self._display_order: List[Tuple[int, int]] = []
        self._diff_rates: Dict[int, float] = {}

    def set_page_clicked_callback(self, callback: Callable[[int], None]) -> None:
        self._on_page_clicked = callback

    def rebuild(
        self,
        toc: List[Tuple[int, str, int]],
        display_order: List[Tuple[int, int]],
        diff_rates: Dict[int, float],
        current_index: int,
    ) -> None:
        """
        display_order: [(base_idx, compare_idx), ...] 即当前展示顺序。
        diff_rates: display_index -> 差异率 (0~1)
        """
        self._display_order = display_order
        self._diff_rates = dict(diff_rates)
        n = len(display_order)
        # 移除旧控件
        if self._tree is not None:
            self._stack_layout.removeWidget(self._tree)
            self._tree.deleteLater()
            self._tree = None
        if self._list is not None:
            self._stack_layout.removeWidget(self._list)
            self._list.deleteLater()
            self._list = None
        if n == 0:
            return
        cb = self._on_page_clicked
        if toc:
            self._tree = self._build_tree(toc, display_order, diff_rates, current_index, cb)
            self._stack_layout.addWidget(self._tree)
        else:
            self._list = QListWidget(self)
            self._list.setMinimumWidth(180)
            self._list.setMaximumWidth(320)
            for i in range(n):
                rate = diff_rates.get(i)
                item = QListWidgetItem(f"第 {i + 1} 页\t{_format_rate(rate)}")
                item.setData(ROLE_DISPLAY_INDEX, i)
                self._list.addItem(item)
            self._list.setCurrentRow(current_index if 0 <= current_index < n else -1)
            def _on_item_clicked(item: QListWidgetItem) -> None:
                if cb is not None:
                    idx = item.data(ROLE_DISPLAY_INDEX)
                    if idx is not None:
                        cb(idx)

            self._list.itemClicked.connect(_on_item_clicked)
            self._apply_list_style()
            self._stack_layout.addWidget(self._list)

    def _build_tree(
        self,
        toc: List[Tuple[int, str, int]],
        display_order: List[Tuple[int, int]],
        diff_rates: Dict[int, float],
        current_index: int,
        on_click: Optional[Callable[[int], None]],
    ) -> QTreeWidget:
        base_to_display = {pair[0]: i for i, pair in enumerate(display_order)}
        tree = QTreeWidget(self)
        tree.setMinimumWidth(180)
        tree.setMaximumWidth(320)
        tree.setColumnCount(2)
        tree.setHeaderLabels(["目录", "差异率"])
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tree.setColumnWidth(1, 56)
        stack: List[Tuple[int, QTreeWidgetItem]] = []
        for level, title, page_0 in toc:
            item = QTreeWidgetItem([title, ""])
            disp = base_to_display.get(page_0, -1)
            if disp >= 0:
                item.setData(0, ROLE_DISPLAY_INDEX, disp)
                rate = diff_rates.get(disp)
                item.setText(1, _format_rate(rate))
                item.setForeground(1, QColor("#c00" if rate is not None and rate > DIFF_RATE_ALERT_THRESHOLD else "#999" if rate is None or rate == 0 else QColor("black")))
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else None
            if parent is None:
                tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            stack.append((level, item))
        def _on_tree_clicked(it: QTreeWidgetItem, col: int) -> None:
            if on_click is not None:
                d = it.data(0, ROLE_DISPLAY_INDEX)
                if d is not None and d >= 0:
                    on_click(d)

        if on_click:
            tree.itemClicked.connect(_on_tree_clicked)
        return tree

    def _apply_list_style(self) -> None:
        if self._list is None:
            return
        for i in range(self._list.count()):
            item = self._list.item(i)
            idx = item.data(ROLE_DISPLAY_INDEX)
            rate = self._diff_rates.get(idx)
            base = item.text().split("\t")[0] if "\t" in item.text() else item.text()
            item.setText(f"{base}\t{_format_rate(rate)}")
            c = "#c00" if rate is not None and rate > DIFF_RATE_ALERT_THRESHOLD else "#999" if rate is None or rate == 0 else "black"
            item.setForeground(QColor(c))

    def set_diff_rates(self, diff_rates: Dict[int, float]) -> None:
        self._diff_rates = dict(diff_rates)
        if self._tree is not None:
            def walk(item: QTreeWidgetItem):
                d = item.data(0, ROLE_DISPLAY_INDEX)
                if d is not None and d >= 0:
                    rate = self._diff_rates.get(d)
                    item.setText(1, _format_rate(rate))
                    item.setForeground(1, QColor("#c00" if rate is not None and rate > DIFF_RATE_ALERT_THRESHOLD else "#999" if rate is None or rate == 0 else QColor("black")))
                for i in range(item.childCount()):
                    walk(item.child(i))
            for i in range(self._tree.topLevelItemCount()):
                walk(self._tree.topLevelItem(i))
        elif self._list is not None:
            self._apply_list_style()

    def set_current_index(self, index: int) -> None:
        n = len(self._display_order)
        if index < 0 or index >= n:
            return
        if self._list is not None:
            self._list.setCurrentRow(index)
        if self._tree is not None:
            def find_and_set(item: QTreeWidgetItem, target: int) -> bool:
                if item.data(0, ROLE_DISPLAY_INDEX) == target:
                    self._tree.setCurrentItem(item)
                    return True
                for i in range(item.childCount()):
                    if find_and_set(item.child(i), target):
                        return True
                return False
            for i in range(self._tree.topLevelItemCount()):
                if find_and_set(self._tree.topLevelItem(i), index):
                    break
