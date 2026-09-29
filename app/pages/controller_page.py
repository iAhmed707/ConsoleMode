"""Controller page: detect and list connected Xbox-style game controllers."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ControllerPage(QWidget):
    """Lists XInput-compatible controllers and their status."""

    status = Signal(str)
    error = Signal(str)

    COLUMNS = ["#", "Controller", "Type"]

    def __init__(self, controller_manager):
        super().__init__()
        self.manager = controller_manager

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("Controller")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        layout.addWidget(title)

        self.subtitle = QLabel(
            "Detects Xbox-style controllers using the Windows XInput API. "
            "Other controller types may not appear here."
        )
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.reload_controllers)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.reload_controllers()

    def reload_controllers(self):
        """Re-detect controllers into the table."""
        if not self.manager.is_available():
            self.subtitle.setText(self.manager.unavailable_reason())
            self._show_empty("Controller detection unavailable.")
            return

        controllers = self.manager.refresh()
        self.table.setRowCount(0)
        if not controllers:
            self._show_empty("No controller detected. Connect one and press Refresh.")
            return

        self.table.setRowCount(len(controllers))
        for row, controller in enumerate(controllers):
            index_item = QTableWidgetItem(str(controller["index"]))
            self.table.setItem(row, 0, index_item)

            name_item = QTableWidgetItem(controller["name"])
            name_item.setForeground(QColor("#D1D5DB"))
            self.table.setItem(row, 1, name_item)

            type_item = QTableWidgetItem(controller["subtype_name"])
            type_item.setForeground(QColor("#93C5FD"))
            self.table.setItem(row, 2, type_item)

        self.status.emit("%d controller(s) detected." % len(controllers))

    def _show_empty(self, text):
        self.table.setRowCount(1)
        item = QTableWidgetItem(text)
        item.setForeground(QColor("#9CA3AF"))
        self.table.setItem(0, 0, item)
        self.table.setSpan(0, 0, 1, len(self.COLUMNS))
