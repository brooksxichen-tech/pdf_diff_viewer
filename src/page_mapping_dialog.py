# -*- coding: utf-8 -*-
"""页面映射设置对话框：基准页码与对比页码对应表。"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

SKIP_LABEL = "无/跳过"


def build_mapping_pairs(
    table: QTableWidget,
    n_base: int,
    n_compare: int,
) -> List[Tuple[int, int]]:
    """
    从表格读取映射，返回 [(base_idx, compare_idx), ...]（仅含非跳过行）。
    """
    pairs: List[Tuple[int, int]] = []
    for row in range(table.rowCount()):
        base_one_based = row + 1
        w = table.cellWidget(row, 1)
        if w is None:
            continue
        if isinstance(w, QComboBox):
            text = w.currentText()
        else:
            text = ""
        if text == SKIP_LABEL or not text.strip():
            continue
        try:
            compare_one_based = int(text.strip())
        except ValueError:
            continue
        if 1 <= compare_one_based <= n_compare:
            pairs.append((row, compare_one_based - 1))
    return pairs


class PageMappingDialog(QDialog):
    """页面映射管理器：左列基准页码，右列对比页码（可下拉或选“无/跳过”）。"""

    def __init__(
        self,
        n_base_pages: int,
        n_compare_pages: int,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("页面映射设置")
        self.setMinimumSize(400, 400)
        self._n_base = n_base_pages
        self._n_compare = n_compare_pages
        self._mapping_pairs: List[Tuple[int, int]] = []

        layout = QVBoxLayout(self)
        self._table = QTableWidget(self._n_base, 2)
        self._table.setHorizontalHeaderLabels(["基准文件页码", "对比文件页码"])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.verticalHeader().setVisible(True)

        # 左列：只读，1-based
        for row in range(self._n_base):
            left = QTableWidgetItem(str(row + 1))
            left.setFlags(left.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, left)
            # 右列：下拉
            combo = QComboBox()
            combo.setEditable(False)
            combo.addItem(SKIP_LABEL)
            for p in range(1, self._n_compare + 1):
                combo.addItem(str(p))
            # 初始 1:1，超出部分选“无/跳过”
            if row < self._n_compare:
                combo.setCurrentIndex(row + 1)
            else:
                combo.setCurrentIndex(0)
            self._table.setCellWidget(row, 1, combo)

        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        self._btn_up = QPushButton("上移行")
        self._btn_down = QPushButton("下移行")
        self._btn_up.clicked.connect(self._move_up)
        self._btn_down.clicked.connect(self._move_down)
        btn_row.addWidget(self._btn_up)
        btn_row.addWidget(self._btn_down)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bbox.accepted.connect(self._on_accept)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def _move_up(self) -> None:
        cr = self._table.currentRow()
        if cr <= 0:
            return
        self._swap_rows(cr - 1, cr)
        self._table.setCurrentCell(cr - 1, 0)

    def _move_down(self) -> None:
        cr = self._table.currentRow()
        if cr < 0 or cr >= self._table.rowCount() - 1:
            return
        self._swap_rows(cr, cr + 1)
        self._table.setCurrentCell(cr + 1, 0)

    def _swap_rows(self, r1: int, r2: int) -> None:
        """交换两行的对比页映射（右列）；左列保持为行号 1,2,..."""
        w1 = self._table.cellWidget(r1, 1)
        w2 = self._table.cellWidget(r2, 1)
        if isinstance(w1, QComboBox) and isinstance(w2, QComboBox):
            i1, i2 = w1.currentIndex(), w2.currentIndex()
            self._table.removeCellWidget(r1, 1)
            self._table.removeCellWidget(r2, 1)
            self._table.setCellWidget(r1, 1, w2)
            self._table.setCellWidget(r2, 1, w1)
            w2.setCurrentIndex(i2)
            w1.setCurrentIndex(i1)

    def _on_accept(self) -> None:
        self._mapping_pairs = build_mapping_pairs(
            self._table, self._n_base, self._n_compare
        )
        if not self._mapping_pairs:
            QMessageBox.warning(
                self,
                "页面映射",
                "至少需要保留一对有效映射（基准页对应对比页）。",
            )
            return
        self.accept()

    def get_mapping_pairs(self) -> List[Tuple[int, int]]:
        """返回 [(base_idx, compare_idx), ...]，按表格行序。"""
        return self._mapping_pairs
