"""Share and persist the custom palette across Pylon's colour pickers."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog


def choose_colour(store, initial, parent, title):
    palette = store.setting("custom_palette")
    palette = palette if isinstance(palette, list) else []
    for index in range(QColorDialog.customCount()):
        colour = QColor(palette[index]) if index < len(palette) and isinstance(palette[index], str) else QColor(Qt.white)
        QColorDialog.setCustomColor(index, colour if colour.isValid() else QColor(Qt.white))
    try:
        # Use Qt's picker on every platform so the saved palette is consistent.
        return QColorDialog.getColor(QColor(initial), parent, title, QColorDialog.DontUseNativeDialog)
    finally:
        # Palette edits are independent of accepting the selected accent/subtitle.
        store.set_setting("custom_palette", [QColorDialog.customColor(i).name(QColor.HexArgb)
                                              for i in range(QColorDialog.customCount())])

