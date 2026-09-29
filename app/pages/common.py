"""Formatting helpers and the placeholder page shared by the UI."""

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

# ---------- monitor formatting ----------
def format_resolution(monitor):
    """"2560 × 1440"."""
    return "%d × %d" % (monitor["width"], monitor["height"])

def format_refresh(monitor):
    """Prefer the exact rate from the CCD API ("179.998 Hz") over the rounded one."""
    exact = monitor.get("refresh_rate_exact")
    if exact:
        # Trim trailing zeros so 60.000 reads as "60 Hz".
        text = ("%.3f" % exact).rstrip("0").rstrip(".")
        return "%s Hz" % text
    if monitor.get("refresh_rate"):
        return "%d Hz" % monitor["refresh_rate"]
    return "—"

def format_hdr(monitor):
    """HDR state as ``(text, colour)`` for the details table."""
    supported = monitor.get("hdr_supported")
    if supported is None:
        return "Unknown", "#9CA3AF"
    if not supported:
        return "Not supported", "#6B7280"
    if monitor.get("hdr_enabled"):
        depth = monitor.get("bits_per_color")
        return ("On · %d-bit" % depth) if depth else "On", "#22C55E"
    return "Supported · off", "#F59E0B"

def describe_display_config(display_config):
    """One-line summary of a profile's display block, for the Profiles page."""
    if not display_config or not display_config.get("monitors"):
        return "No display settings saved."

    monitors = display_config["monitors"]
    primary_name = display_config.get("primary")
    primary = next((m for m in monitors if m.get("name") == primary_name), None)

    parts = ["%d display%s" % (len(monitors), "" if len(monitors) == 1 else "s")]
    if primary:
        parts.append("primary: %s (%s)" % (
            primary.get("label") or primary.get("name"), format_resolution(primary)
        ))

    hdr_on = [m.get("label") or m.get("name")
              for m in monitors if m.get("hdr_enabled")]
    if hdr_on:
        parts.append("HDR on: %s" % ", ".join(hdr_on))

    return "  ·  ".join(parts)

# ---------- placeholder ----------
class PlaceholderPage(QWidget):
    """Used for the sections that are not built yet."""

    def __init__(self, title):
        super().__init__()
        layout = QVBoxLayout(self)
        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 22, QFont.Bold))
        subtitle = QLabel("Coming Soon...")
        subtitle.setFont(QFont("Segoe UI", 12))
        layout.addWidget(title_label)
        layout.addWidget(subtitle)
        layout.addStretch()
