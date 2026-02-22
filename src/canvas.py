# -*- coding: utf-8 -*-
"""可缩放、拖拽平移的画布；以及同步查看和灵活对比视图。"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap, QWheelEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


def ndarray_to_qimage(rgb: np.ndarray) -> QImage:
    """(H, W, 3) uint8 RGB -> QImage。灰度图可传 (H,W)，将按 RGB 三通道复制。"""
    if rgb.ndim == 2:
        rgb = np.stack([rgb, rgb, rgb], axis=-1)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        return QImage()
    h, w = rgb.shape[:2]
    if np.uint8 != rgb.dtype:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    rgb = np.ascontiguousarray(rgb)
    qimg = QImage(
        rgb.data,
        w,
        h,
        w * 3,
        QImage.Format.Format_RGB888,
    )
    return qimg.copy()


class DiffCanvas(QGraphicsView):
    """支持滚轮缩放、左键拖拽平移的画布。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._last_pos = None
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(self.palette().brush(self.backgroundRole()))
        self.setMinimumSize(400, 300)

    def set_diff_image(self, rgb: np.ndarray) -> None:
        """设置要显示的图像 (H, W, 3) uint8 RGB 或 (H, W) 灰度。"""
        qimg = ndarray_to_qimage(rgb)
        if qimg.isNull():
            return
        pix = QPixmap.fromImage(qimg)
        if self._pixmap_item is None:
            self._pixmap_item = self.scene().addPixmap(pix)
        else:
            self._pixmap_item.setPixmap(pix)
        self.scene().setSceneRect(self._pixmap_item.boundingRect())
        self.reset_transform()

    def reset_transform(self) -> None:
        if self._pixmap_item is None:
            return
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.2
        if event.angleDelta().y() > 0:
            self.scale(factor, factor)
        else:
            self.scale(1.0 / factor, 1.0 / factor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_pos = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._last_pos is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            delta = event.position() - self._last_pos
            self._last_pos = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_pos = None
        super().mouseReleaseEvent(event)


class SyncDiffCanvas(DiffCanvas):
    """在滚动/缩放时可与其他画布同步。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._partner: Optional[SyncDiffCanvas] = None
        self._sync_group: Optional[SyncGroup] = None

    def set_partner(self, partner: SyncDiffCanvas) -> None:
        self._partner = partner
        self._connect_scroll_sync()

    def set_sync_group(self, group: Optional["SyncGroup"]) -> None:
        self._sync_group = group

    def _connect_scroll_sync(self) -> None:
        if self._partner is None:
            return
        for bar_name in ("verticalScrollBar", "horizontalScrollBar"):
            my_bar = getattr(self, bar_name)()
            other_bar = getattr(self._partner, bar_name)()

            def sync_to_other(_my, _other):
                def sync(value: int) -> None:
                    _other.blockSignals(True)
                    _other.setValue(value)
                    _other.blockSignals(False)

                return sync

            my_bar.valueChanged.connect(sync_to_other(my_bar, other_bar))
            other_bar.valueChanged.connect(sync_to_other(other_bar, my_bar))

    def wheelEvent(self, event: QWheelEvent) -> None:
        super().wheelEvent(event)
        if self._sync_group:
            self._sync_group.sync_from(self)


class SyncGroup:
    """将多个 SyncDiffCanvas 的滚动与缩放保持一致。"""

    def __init__(self, views: List[SyncDiffCanvas]) -> None:
        self._views = list(views)
        self._block = False
        for v in self._views:
            v.set_sync_group(self)
        self._connect_scroll_bars()

    def _connect_scroll_bars(self) -> None:
        for v in self._views:
            v.verticalScrollBar().valueChanged.connect(
                lambda val, src=v: self._on_scroll(src, "v", val)
            )
            v.horizontalScrollBar().valueChanged.connect(
                lambda val, src=v: self._on_scroll(src, "h", val)
            )

    def disconnect_all(self) -> None:
        for v in self._views:
            v.set_sync_group(None)
        self._views.clear()

    def _on_scroll(self, source: SyncDiffCanvas, orientation: str, value: int) -> None:
        if self._block:
            return
        self._block = True
        for w in self._views:
            if w is source:
                continue
            bar = w.verticalScrollBar() if orientation == "v" else w.horizontalScrollBar()
            bar.blockSignals(True)
            bar.setValue(value)
            bar.blockSignals(False)
        self._block = False

    def sync_from(self, source: SyncDiffCanvas) -> None:
        if self._block:
            return
        self._block = True
        t = source.transform()
        v = source.verticalScrollBar().value()
        h = source.horizontalScrollBar().value()
        for w in self._views:
            if w is source:
                continue
            w.setTransform(t)
            w.verticalScrollBar().setValue(v)
            w.horizontalScrollBar().setValue(h)
        self._block = False


class FlexibleCompareView(QWidget):
    """
    根据勾选动态在 QSplitter 中显示 1～3 个视图；默认仅叠加差异图。
    勾选时将该视图 addWidget 加入 splitter，取消勾选时 setParent(self) 移出。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spl = QSplitter(Qt.Orientation.Horizontal)
        self._views: List[SyncDiffCanvas] = [
            SyncDiffCanvas(self),
            SyncDiffCanvas(self),
            SyncDiffCanvas(self),
        ]
        self._sync_group: Optional[SyncGroup] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._spl)
        self.set_panes(False, True, False)

    def set_panes(self, show_base: bool, show_overlay: bool, show_compare: bool) -> None:
        if not (show_base or show_overlay or show_compare):
            show_overlay = True
        if self._sync_group:
            self._sync_group.disconnect_all()
            self._sync_group = None
        while self._spl.count() > 0:
            w = self._spl.widget(0)
            w.setParent(self)
        order = [(self._views[0], show_base), (self._views[1], show_overlay), (self._views[2], show_compare)]
        for v, show in order:
            if show:
                self._spl.addWidget(v)
        for i in range(self._spl.count()):
            self._spl.setStretchFactor(i, 1)
        active = [v for v, show in order if show]
        if len(active) >= 2:
            self._sync_group = SyncGroup(active)

    def view_base(self) -> SyncDiffCanvas:
        return self._views[0]

    def view_overlay(self) -> SyncDiffCanvas:
        return self._views[1]

    def view_compare(self) -> SyncDiffCanvas:
        return self._views[2]

    def set_base_image(self, img: np.ndarray) -> None:
        self._views[0].set_diff_image(img)

    def set_overlay_image(self, img: np.ndarray) -> None:
        self._views[1].set_diff_image(img)

    def set_compare_image(self, img: np.ndarray) -> None:
        self._views[2].set_diff_image(img)

    def set_transform_from(self, source: DiffCanvas) -> None:
        t = source.transform()
        v = source.verticalScrollBar().value()
        h = source.horizontalScrollBar().value()
        for w in self._views:
            w.setTransform(t)
            w.verticalScrollBar().setValue(v)
            w.horizontalScrollBar().setValue(h)
