"""Digital-twin timeline tab (V5, section 28)."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from src.models.timeline import build_timeline
from src.utils.history_store import HistoryStore


class TimelineTab(QWidget):
    """Chronological view of the wearer's longitudinal record."""

    def __init__(self, store: HistoryStore, parent=None):
        super().__init__(parent)
        self.store = store
        layout = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel("Digital Twin Timeline — chronological record of monitoring, calibrations, "
                       "anomalies, checkpoints and manual inputs. Research view, not a diagnosis.")
        title.setWordWrap(True)
        title.setObjectName("SmallMuted")
        head.addWidget(title, 1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        head.addWidget(self.refresh_btn)
        layout.addLayout(head)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        events = build_timeline(self.store)
        if not events:
            item = QListWidgetItem("No timeline entries yet — start a session, calibrate, or log data.")
            self.list.addItem(item)
            return
        for e in events:
            text = f"[{e.day}] {e.title}"
            if e.detail:
                text += f" — {e.detail}"
            item = QListWidgetItem(text)
            from src.ui import theme as _theme
            color = {"ok": _theme.GREEN, "warn": _theme.YELLOW, "alert": _theme.RED}.get(e.severity, _theme.TEXT_MUTED)
            item.setForeground(QColor(color))
            self.list.addItem(item)
