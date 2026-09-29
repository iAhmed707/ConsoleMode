"""Audio page: list output devices and choose the Windows default."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

class AudioPage(QWidget):
    """Lists active output devices and sets the default."""

    # Emitted with a one-line result for the main window's status bar.
    status = Signal(str)
    # Emitted when switching the default device fails, for the log.
    error = Signal(str)

    COLUMNS = ["Device", "Status"]

    def __init__(self, audio_manager):
        super().__init__()
        self.audio = audio_manager

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("Audio")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        layout.addWidget(title)

        self.subtitle = QLabel("Choose which device Windows uses for sound output.")
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
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self.update_buttons)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.set_default_btn = QPushButton("Set as default")
        self.set_default_btn.clicked.connect(self.set_default)
        buttons.addWidget(self.set_default_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.reload_devices)
        buttons.addWidget(refresh_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.reload_devices()

    def reload_devices(self):
        """Re-enumerate output devices into the table."""
        if not self.audio.is_available():
            self.subtitle.setText(self.audio.unavailable_reason())
            self.table.setRowCount(0)
            self.set_default_btn.setEnabled(False)
            return

        devices = self.audio.refresh()
        self.table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            name_item = QTableWidgetItem(device["name"])
            name_item.setData(Qt.UserRole, device)
            self.table.setItem(row, 0, name_item)

            status_item = QTableWidgetItem("Default" if device["is_default"] else "")
            if device["is_default"]:
                status_item.setForeground(QColor("#22C55E"))
            self.table.setItem(row, 1, status_item)

            if device["is_default"]:
                self.table.selectRow(row)

        self.update_buttons()

    def selected_device(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def update_buttons(self):
        device = self.selected_device()
        self.set_default_btn.setEnabled(bool(device) and not device["is_default"])

    def set_default(self):
        device = self.selected_device()
        if device is None:
            return

        ok, message = self.audio.set_default_device(device["id"], device["name"])
        self.reload_devices()
        if ok:
            self.status.emit(message)
        else:
            self.error.emit(message)
            QMessageBox.warning(self, "Could not change audio device", message)
