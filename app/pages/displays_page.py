"""Displays page: layout diagram, per-monitor details, and applying changes."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
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

from app.pages.common import format_hdr, format_refresh, format_resolution

# Seconds to wait for the user to confirm a display change before undoing it,
# mirroring what Windows does in its own Display settings.
REVERT_SECONDS = 15

class MonitorRectItem(QGraphicsRectItem):
    """A clickable monitor rectangle. Carries the monitor dict it was drawn from."""

    def __init__(self, monitor, x, y, width, height, on_click=None, parent=None):
        super().__init__(x, y, width, height, parent)
        self.monitor = monitor
        self.monitor_id = monitor["id"]
        self.device_name = monitor["name"]
        self.is_primary = monitor.get("is_primary", False)
        self._on_click = on_click

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.ItemIsFocusable, True)

        self.normal_brush = QBrush(QColor("#3B82F6")) if self.is_primary else QBrush(QColor("#2C2C2C"))
        self.setBrush(self.normal_brush)
        self.setPen(QPen(QColor("#555555"), 2))

        # QGraphicsItem is not a QObject, so PySide6 does not hand ownership of
        # child items to the C++ parent. Every child must be kept referenced
        # from Python or it is garbage collected and never drawn.
        self.text_items = []

        # Text sits on a blue fill for the primary monitor and a dark fill for
        # the rest, so the secondary colours have to differ to stay legible.
        if self.is_primary:
            caption_colour, rate_colour = QColor("#EFF6FF"), QColor("#DBEAFE")
            hdr_on, hdr_off = QColor("#BBF7D0"), QColor("#BFDBFE")
        else:
            caption_colour, rate_colour = QColor("#D1D5DB"), QColor("#9CA3AF")
            hdr_on, hdr_off = QColor("#22C55E"), QColor("#6B7280")

        self.label = self._add_text(str(self.monitor_id), 16, Qt.white, bold=True)
        self.label.setPos(
            x + width / 2 - self.label.boundingRect().width() / 2,
            y + height / 2 - self.label.boundingRect().height() / 2,
        )

        # Resolution caption under the number, so the diagram is readable
        # without cross-referencing the table.
        caption = self._add_text(format_resolution(monitor), 9, caption_colour)
        caption.setPos(
            x + width / 2 - caption.boundingRect().width() / 2,
            y + height / 2 + 16,
        )

        # Refresh rate under that, in the same spirit.
        rate = self._add_text(format_refresh(monitor), 8, rate_colour)
        rate.setPos(
            x + width / 2 - rate.boundingRect().width() / 2,
            y + height / 2 + 34,
        )

        # Corner badges only fit on reasonably large rectangles.
        if height >= 70:
            if self.is_primary:
                badge = self._add_text("Primary", 10, QColor("#FFFFFF"), bold=True)
                badge.setPos(x + 8, y + height - badge.boundingRect().height() - 6)

            # HDR marker, so an HDR-on display is obvious at a glance:
            # bright when active, dim when merely supported.
            if monitor.get("hdr_enabled"):
                hdr = self._add_text("HDR", 9, hdr_on, bold=True)
                hdr.setPos(x + 8, y + 4)
            elif monitor.get("hdr_supported"):
                hdr = self._add_text("HDR", 9, hdr_off, bold=True)
                hdr.setPos(x + 8, y + 4)

    def _add_text(self, text, point_size, colour, bold=False):
        """Create a child label and keep a reference to it (see __init__)."""
        item = QGraphicsTextItem(text, self)
        item.setDefaultTextColor(colour)
        font = item.font()
        font.setPointSize(point_size)
        font.setBold(bold)
        item.setFont(font)
        self.text_items.append(item)
        return item

    def select(self):
        self.setPen(QPen(QColor("#FFFFFF"), 4))

    def deselect(self):
        self.setPen(QPen(QColor("#555555"), 2))

    def mousePressEvent(self, event):
        """Clicking a rectangle selects it."""
        super().mousePressEvent(event)
        if self._on_click:
            self._on_click(self)

class GraphicalDisplaysPage(QWidget):
    """Monitor layout diagram plus a per-monitor details table.

    The diagram and the table are two views of the same selection: clicking a
    rectangle highlights its row and vice versa.
    """

    # Emitted with a one-line result for the main window's status bar.
    status = Signal(str)
    # Emitted when a Windows display API call fails, for the log.
    error = Signal(str)

    # Details table columns
    COLUMNS = ["#", "Monitor", "Resolution", "Refresh rate", "HDR",
               "Connection", "Position", "Role", "Device"]

    def __init__(self, display_manager):
        super().__init__()
        self.manager = display_manager
        self.selected_monitor = None
        self.monitor_items = []
        self.monitors = []
        self.selected_name = None

        # EnumDisplaySettings walks 100+ modes per monitor, so results are
        # cached and only rebuilt when the selection changes.
        self._modes_cache = {}
        self._syncing = False

        # Pending "keep or revert" confirmation; see _schedule_confirm_or_revert.
        self._confirm_timer = None

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)

        label = QLabel("Select a display to see its details and change its settings.")
        label.setWordWrap(True)
        main_layout.addWidget(label)

        self.view = QGraphicsView()
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setStyleSheet("background: #1E1E1E; border-radius: 8px;")
        self.view.setMinimumHeight(230)
        self.scene = QGraphicsScene()
        self.view.setScene(self.scene)
        main_layout.addWidget(self.view)

        controls_layout = QHBoxLayout()
        self.identify_btn = QPushButton("Identify")
        self.identify_btn.clicked.connect(self.identify_monitor)
        controls_layout.addWidget(self.identify_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.reload_monitors)
        controls_layout.addWidget(self.refresh_btn)

        self.primary_btn = QPushButton("Set as primary")
        self.primary_btn.clicked.connect(self.apply_primary)
        controls_layout.addWidget(self.primary_btn)

        self.hdr_btn = QPushButton("Toggle HDR")
        self.hdr_btn.clicked.connect(self.toggle_hdr)
        controls_layout.addWidget(self.hdr_btn)

        controls_layout.addStretch()
        main_layout.addLayout(controls_layout)

        # ---------- details ----------
        details_label = QLabel("Display details")
        details_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        main_layout.addWidget(details_label)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        # Keep every monitor on one line; long names elide instead of wrapping.
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        # Absorb any slack in the monitor name rather than the last column,
        # otherwise the device name gets clipped behind a scrollbar.
        header.setSectionResizeMode(self.COLUMNS.index("Monitor"), QHeaderView.Stretch)
        header.setStretchLastSection(False)
        self.table.itemSelectionChanged.connect(self.on_row_selected)
        main_layout.addWidget(self.table)

        # ---------- supported resolutions of the selected monitor ----------
        modes_layout = QHBoxLayout()
        self.modes_label = QLabel("Supported resolutions:")
        modes_layout.addWidget(self.modes_label)
        self.resolution_combo = QComboBox()
        self.resolution_combo.setMinimumWidth(240)
        modes_layout.addWidget(self.resolution_combo)

        self.apply_btn = QPushButton("Apply resolution")
        self.apply_btn.clicked.connect(self.apply_resolution)
        modes_layout.addWidget(self.apply_btn)
        modes_layout.addStretch()
        main_layout.addLayout(modes_layout)

        # The diagram absorbs spare vertical space; everything else is fixed.
        main_layout.setStretchFactor(self.view, 1)

        self.reload_monitors()

    # ---------- data ----------
    def reload_monitors(self):
        """Re-enumerate the monitors, then rebuild the diagram and the table."""
        self.monitors = self.manager.refresh()
        self._modes_cache.clear()

        # Keep the current selection if that monitor is still connected.
        names = {m["name"] for m in self.monitors}
        if self.selected_name not in names:
            primary = next((m for m in self.monitors if m["is_primary"]), None)
            self.selected_name = primary["name"] if primary else (
                self.monitors[0]["name"] if self.monitors else None
            )

        self.rebuild_scene()
        self.populate_table()
        self.populate_modes()
        self.update_buttons()

    # ---------- diagram ----------
    def rebuild_scene(self):
        """Draw the monitor rectangles, scaled to fit the view."""
        self.scene.clear()
        self.monitor_items = []
        self.selected_monitor = None

        if not self.monitors:
            text = self.scene.addText("No monitors detected. Click Refresh.")
            text.setDefaultTextColor(Qt.white)
            return

        min_x = min(m["x"] for m in self.monitors)
        max_x = max(m["x"] + m["width"] for m in self.monitors)
        min_y = min(m["y"] for m in self.monitors)
        max_y = max(m["y"] + m["height"] for m in self.monitors)

        total_width = max_x - min_x
        total_height = max_y - min_y

        padding = 50
        scene_width = total_width + padding * 2
        scene_height = total_height + padding * 2

        view_width = self.view.width() - 40
        view_height = self.view.height() - 40
        if view_width <= 0 or view_height <= 0:
            view_width, view_height = 800, 400

        scale_x = view_width / scene_width
        scale_y = view_height / scene_height
        scale = min(scale_x, scale_y, 1.0)  # only scale down to fit

        for mon in self.monitors:
            x = (mon["x"] - min_x + padding) * scale
            y = (mon["y"] - min_y + padding) * scale
            w = mon["width"] * scale
            h = mon["height"] * scale

            rect_item = MonitorRectItem(mon, x, y, w, h, on_click=self.on_rect_clicked)
            self.scene.addItem(rect_item)
            self.monitor_items.append(rect_item)

        self.scene.setSceneRect(0, 0, scene_width * scale, scene_height * scale)

        # Re-apply the highlight, since the items were just recreated.
        for item in self.monitor_items:
            if item.device_name == self.selected_name:
                self.selected_monitor = item
                item.select()
                break

    # ---------- table ----------
    def populate_table(self):
        """One row per monitor: resolution, refresh rate, HDR and connection."""
        self._syncing = True
        self.table.setRowCount(len(self.monitors))

        for row, mon in enumerate(self.monitors):
            hdr_text, hdr_colour = format_hdr(mon)
            cells = [
                str(mon["id"]),
                mon.get("label") or "Unknown",
                format_resolution(mon),
                format_refresh(mon),
                hdr_text,
                mon.get("connection") or "—",
                "%d, %d" % (mon["x"], mon["y"]),
                "Primary" if mon["is_primary"] else "",
                mon["name"],
            ]

            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if self.COLUMNS[column] == "HDR":
                    item.setForeground(QColor(hdr_colour))
                elif self.COLUMNS[column] == "Role" and mon["is_primary"]:
                    # Light blue: legible on both the row and selection colour.
                    item.setForeground(QColor("#93C5FD"))
                elif self.COLUMNS[column] == "Device":
                    item.setForeground(QColor("#9CA3AF"))
                self.table.setItem(row, column, item)

            if mon["name"] == self.selected_name:
                self.table.selectRow(row)

        self._syncing = False
        self._fit_table_height()

    def _fit_table_height(self):
        """Size the table to its rows so it does not leave a dead grey block.

        The diagram keeps the leftover vertical space instead.
        """
        self.table.resizeRowsToContents()
        height = self.table.horizontalHeader().height()
        for row in range(self.table.rowCount()):
            height += self.table.rowHeight(row)
        height += 2 * self.table.frameWidth()
        # Always reserve the horizontal scrollbar: whether it appears depends on
        # font metrics we cannot know here, and coming up short clips a row.
        height += self.table.horizontalScrollBar().sizeHint().height()
        # Guard against a resize loop: setFixedHeight re-triggers layout.
        if self.table.maximumHeight() != height:
            self.table.setFixedHeight(height)

    # ---------- supported resolutions ----------
    def populate_modes(self):
        """Fill the resolution dropdown for the selected monitor."""
        self.resolution_combo.clear()

        monitor = self.selected_monitor_data()
        if monitor is None:
            self.modes_label.setText("Supported resolutions:")
            return

        name = monitor["name"]
        if name not in self._modes_cache:
            self._modes_cache[name] = self.manager.get_available_modes(name)
        modes = self._modes_cache[name]

        self.modes_label.setText(
            "Supported resolutions — Display %d, %s (%d modes):"
            % (monitor["id"], monitor.get("label") or name, len(modes))
        )

        current = (monitor["width"], monitor["height"], monitor["refresh_rate"])
        for width, height, refresh in modes:
            self.resolution_combo.addItem(
                "%d × %d  @ %d Hz" % (width, height, refresh), (width, height, refresh)
            )
            if (width, height, refresh) == current:
                self.resolution_combo.setCurrentIndex(self.resolution_combo.count() - 1)

    # ---------- selection ----------
    def selected_monitor_data(self):
        """The monitor dict behind the current selection, or None."""
        for mon in self.monitors:
            if mon["name"] == self.selected_name:
                return mon
        return None

    def on_rect_clicked(self, item):
        """Diagram -> table."""
        self.select_monitor(item)

    def on_row_selected(self):
        """Table -> diagram."""
        if self._syncing:
            return
        row = self.table.currentRow()
        if row < 0 or row >= len(self.monitors):
            return
        self.select_by_name(self.monitors[row]["name"])

    def select_monitor(self, item):
        """Highlight a rectangle and sync the table to it."""
        if self.selected_monitor:
            self.selected_monitor.deselect()
        self.selected_monitor = item

        if item is None:
            return
        item.select()
        self.selected_name = item.device_name

        self._syncing = True
        for row, mon in enumerate(self.monitors):
            if mon["name"] == self.selected_name:
                self.table.selectRow(row)
                break
        self._syncing = False

        self.populate_modes()
        self.update_buttons()

    def select_by_name(self, device_name):
        """Select a monitor by its ``\\\\.\\DISPLAYn`` name."""
        for item in self.monitor_items:
            if item.device_name == device_name:
                self.select_monitor(item)
                return
        # The diagram may not be built yet; remember the choice anyway.
        self.selected_name = device_name
        self.populate_modes()
        self.update_buttons()

    def update_buttons(self):
        """Enable/label the action buttons for the current selection."""
        monitor = self.selected_monitor_data()
        has_selection = monitor is not None

        self.primary_btn.setEnabled(has_selection and not monitor["is_primary"])
        self.apply_btn.setEnabled(has_selection)

        supports_hdr = bool(monitor and monitor.get("hdr_supported"))
        self.hdr_btn.setEnabled(supports_hdr)
        if not supports_hdr:
            self.hdr_btn.setText("HDR not supported")
        elif monitor.get("hdr_enabled"):
            self.hdr_btn.setText("Turn HDR off")
        else:
            self.hdr_btn.setText("Turn HDR on")

    # ---------- actions ----------
    def identify_monitor(self):
        """Flash the selected monitor white for 300 ms."""
        item = self.selected_monitor
        if not item:
            return
        original_brush = item.brush()
        item.setBrush(QBrush(Qt.white))
        # Bind the item now: restoring self.selected_monitor later would repaint
        # the wrong rectangle if the selection changed within the 300 ms.
        QTimer.singleShot(300, lambda: item.setBrush(original_brush))

    def apply_resolution(self):
        """Change the selected monitor to the mode chosen in the dropdown."""
        monitor = self.selected_monitor_data()
        mode = self.resolution_combo.currentData()
        if monitor is None or mode is None:
            return

        width, height, refresh = mode
        if (width, height, refresh) == (monitor["width"], monitor["height"],
                                       monitor["refresh_rate"]):
            self.status.emit("That is already the current mode.")
            return

        if not self._confirm(
            "Change %s to %d × %d @ %d Hz?"
            % (monitor.get("label") or monitor["name"], width, height, refresh)
        ):
            return

        previous = self.manager.capture_layout()
        ok, message = self.manager.set_resolution(monitor["name"], width, height, refresh)
        self.reload_monitors()

        if ok:
            self._schedule_confirm_or_revert(
                previous, message,
                "Keep %s at %d × %d @ %d Hz?"
                % (monitor.get("label") or monitor["name"], width, height, refresh),
            )
        else:
            self.error.emit(message)
            QMessageBox.warning(self, "Could not change resolution", message)

    def apply_primary(self):
        """Make the selected monitor the primary display."""
        monitor = self.selected_monitor_data()
        if monitor is None or monitor["is_primary"]:
            return

        name = monitor.get("label") or monitor["name"]
        if not self._confirm("Make %s the primary display?" % name):
            return

        previous = self.manager.capture_layout()
        ok, message = self.manager.set_primary(monitor["name"])
        self.reload_monitors()

        if ok:
            self._schedule_confirm_or_revert(
                previous, message, "Keep %s as the primary display?" % name
            )
        else:
            self.error.emit(message)
            QMessageBox.warning(self, "Could not set primary display", message)

    def toggle_hdr(self):
        """Turn HDR on or off for the selected monitor."""
        monitor = self.selected_monitor_data()
        if monitor is None or not monitor.get("hdr_supported"):
            return

        wanted = not monitor.get("hdr_enabled")
        ok, message = self.manager.set_hdr(monitor["name"], wanted)
        self.reload_monitors()
        if ok:
            self.status.emit(message)
        else:
            self.error.emit(message)
            QMessageBox.warning(self, "Could not change HDR", message)

    # ---------- confirmation ----------
    # Seconds to let the desktop settle after a mode change before asking,
    # so the popup is not created while Windows is still re-laying out windows.
    CONFIRM_DELAY_MS = 600

    def _confirm(self, question):
        answer = QMessageBox.question(
            self, "Apply display change", question,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _schedule_confirm_or_revert(self, previous_layout, success_message, question):
        """Show the keep/revert popup once the display change has settled.

        ``ChangeDisplaySettingsExW`` returns before Windows has finished its
        own re-layout (windows are repositioned, the DWM re-composites, the
        screen can briefly blank). Opening the popup in that instant can
        leave it behind the main window or positioned with stale screen
        geometry - the user never sees it, the countdown runs out and the
        settings silently revert. A short delay plus the explicit raise in
        :meth:`_confirm_or_revert` makes sure the popup is actually seen,
        whichever direction the resolution changed.
        """
        if self._confirm_timer is not None:
            self._confirm_timer.stop()
            self._confirm_timer.deleteLater()

        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.timeout.connect(
            lambda: self._confirm_or_revert(previous_layout, success_message, question)
        )
        self._confirm_timer.start(self.CONFIRM_DELAY_MS)

    def _confirm_or_revert(self, previous_layout, success_message, question):
        """Ask whether to keep a change, undoing it if there is no answer.

        A bad mode can leave a screen blank, in which case the user cannot
        click anything - so silence is treated as "revert", the same way
        Windows' own display settings behave.

        The box is parented to the top-level window, centred on that window's
        screen and forced to the foreground, so a display-mode switch cannot
        leave it hidden behind the app or parked off-screen.
        """
        window = self.window()
        box = QMessageBox(window if window is not None else self)
        box.setWindowTitle("Keep these display settings?")
        box.setIcon(QMessageBox.Question)
        box.setText(question)
        keep_button = box.addButton("Keep changes", QMessageBox.AcceptRole)
        box.addButton("Revert", QMessageBox.RejectRole)

        remaining = {"seconds": REVERT_SECONDS}

        def update_text():
            box.setInformativeText("Reverting in %d second%s if you do not respond."
                                   % (remaining["seconds"],
                                      "" if remaining["seconds"] == 1 else "s"))

        def tick():
            remaining["seconds"] -= 1
            if remaining["seconds"] <= 0:
                box.reject()  # closes the dialog; treated as "revert" below
            else:
                update_text()

        timer = QTimer(box)
        timer.timeout.connect(tick)
        update_text()

        # Centre on the window's *current* screen instead of trusting
        # geometry that may still describe the pre-change desktop.
        box.adjustSize()
        screen = window.screen() if window is not None else None
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is not None:
            centre = screen.availableGeometry().center()
            box.move(centre - box.rect().center())

        box.show()
        box.raise_()
        box.activateWindow()
        # The mode switch can steal the foreground right after show(); a
        # second raise a beat later takes it back.
        raise_timer = QTimer(box)
        raise_timer.setSingleShot(True)
        raise_timer.timeout.connect(lambda: (box.raise_(), box.activateWindow()))
        raise_timer.start(200)

        timer.start(1000)

        box.exec()
        timer.stop()

        if box.clickedButton() is keep_button:
            self.status.emit(success_message)
            return

        ok, revert_message = self.manager.apply_layout(previous_layout["monitors"])
        self.reload_monitors()
        self.status.emit("Reverted. %s" % revert_message if not ok else "Reverted display settings.")

    # ---------- events ----------
    def showEvent(self, event):
        """Re-measure the table once the stylesheet's cell padding is applied.

        Row heights measured in __init__ are too small, because the page is not
        yet parented to the main window and so has not inherited its style.
        """
        super().showEvent(event)
        self._fit_table_height()

    def resizeEvent(self, event):
        """Re-scale the diagram; the table only needs re-measuring."""
        super().resizeEvent(event)
        self.rebuild_scene()
        self._fit_table_height()
