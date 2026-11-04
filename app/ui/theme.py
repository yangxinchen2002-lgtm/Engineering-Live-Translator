"""Shared desktop styling; no changes to the user's overlay colors or type size."""
from pathlib import Path

_ASSETS=(Path(__file__).parent/'assets').as_posix()

STYLE='''
QMainWindow, QDialog { background:#f4f6fa; color:#1d2b42; }
QWidget { color:#1d2b42; }
QFrame#card, QFrame#sidebar, QFrame#subtitleCard, QFrame#toolCard {
    background:white; border:1px solid #e2e7ef; border-radius:16px;
}
QFrame#translationPanel { background:#f2f7fc; border:0; border-radius:12px; }
QLabel#muted { color:#77849a; }
QLabel#eyebrow { color:#6e7f9a; font-size:8pt; font-weight:600; letter-spacing:1px; }
QLabel#brandMark { background:transparent; }
QLabel#sectionTitle { color:#24364f; font-size:11pt; font-weight:600; }
QLabel#captionLabel { color:#8190a5; font-size:8pt; font-weight:600; letter-spacing:1px; }
QLabel#translationLabel { color:#52759a; font-size:8pt; font-weight:600; letter-spacing:1px; }
QLabel#badge { background:#e9efff; color:#3b61d9; border-radius:12px; padding:8px 13px; font-size:9pt; }
QLabel#guide { color:#5f7394; background:#eaf0fb; border:1px solid #e2eaf8; border-radius:10px; padding:10px 14px; }
QLabel#notice { color:#566c8a; background:#eaf0f8; border:1px solid #e1e9f4; border-radius:10px; padding:10px 14px; }
QLabel#notice[severity="error"] { color:#a74354; background:#fff0f2; border-color:#f5dce2; }
QLabel#state { color:#667e9e; background:#f0f4fa; border-radius:9px; padding:5px 10px; font-size:9pt; }
QLabel#timer { color:#8190a5; font-size:9pt; }
QLabel#usagePanel { color:#4a6388; background:#eaf0fb; border:1px solid #dfe8f8; border-radius:10px; padding:12px 14px; }
QPushButton {
    background:white; border:1px solid #dfe5ef; border-radius:8px;
    padding:8px 12px; color:#3e506b;
}
QPushButton:hover { background:#f1f5ff; border-color:#bacaf4; color:#3459d5; }
QPushButton:pressed { background:#e5edff; border-color:#9fb6ee; }
QPushButton:focus { border-color:#6e90f2; }
QPushButton:disabled { background:#f5f7fa; color:#a6b0c0; border-color:#e8ecf2; }
QPushButton#primary { background:#3b61e9; color:white; border:1px solid #3b61e9; font-weight:600; }
QPushButton#primary:hover { background:#2d50d2; border-color:#2d50d2; }
QPushButton#primary:pressed { background:#2446c3; }
QPushButton#primary:disabled { background:#e0e7fb; border-color:#e0e7fb; color:#97a8d3; }
QPushButton#stop { color:#ae4a59; background:#fff7f8; border-color:#f0dfe4; }
QPushButton#stop:hover { background:#ffedef; border-color:#e6bdc7; }
QPushButton#stop:disabled { color:#abb3c0; background:#f5f7fa; border-color:#e8ecf2; }
QPushButton#quiet { background:transparent; border-color:transparent; padding:6px 9px; color:#6d7d96; }
QPushButton#quiet:hover { background:#e9effa; color:#365bd5; }
QComboBox, QLineEdit {
    background:white; border:1px solid #dce3ee; border-radius:8px;
    padding:8px 12px; min-height:20px; selection-background-color:#e6edff; selection-color:#2447ae;
}
QComboBox { padding-right:32px; }
QComboBox:hover, QLineEdit:hover { border-color:#b6c6df; }
QComboBox:focus, QLineEdit:focus { border-color:#6e90f2; }
QComboBox:disabled, QLineEdit:disabled { color:#a0acbd; background:#f6f8fb; border-color:#e7ecf3; }
QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:top right; width:28px; border:0; }
QComboBox::down-arrow { image:url("__ASSETS__/chevron-down.svg"); width:12px; height:12px; }
QComboBox QAbstractItemView {
    background:white; border:1px solid #dce3ee; border-radius:6px; padding:4px;
    selection-background-color:#e9efff; selection-color:#3155c6; outline:0;
}
QCheckBox { spacing:8px; }
QCheckBox:disabled { color:#a0acbd; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #c8d2e2; border-radius:4px; background:white; }
QCheckBox::indicator:hover { border-color:#7192ee; background:#f3f6ff; }
QCheckBox::indicator:checked { background:#3b61e9; border-color:#3b61e9; image:url("__ASSETS__/check.svg"); }
QCheckBox::indicator:disabled { border-color:#e0e6ef; background:#f1f4f8; }
QCheckBox::indicator:checked:disabled { background:#a4b5e7; border-color:#a4b5e7; }
QSpinBox {
    background:white; border:1px solid #dce3ee; border-radius:7px;
    padding:5px 25px 5px 8px; min-height:20px; selection-background-color:#e6edff; selection-color:#2447ae;
}
QSpinBox:focus { border-color:#6e90f2; }
QSpinBox:disabled { color:#a0acbd; background:#f6f8fb; }
QSpinBox::up-button { subcontrol-origin:border; subcontrol-position:top right; width:20px; border-left:1px solid #e5eaf2; }
QSpinBox::down-button { subcontrol-origin:border; subcontrol-position:bottom right; width:20px; border-left:1px solid #e5eaf2; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background:#eaf0ff; }
QSpinBox::up-arrow { image:url("__ASSETS__/chevron-up.svg"); width:10px; height:10px; }
QSpinBox::down-arrow { image:url("__ASSETS__/chevron-down.svg"); width:10px; height:10px; }
QSlider::groove:horizontal { height:4px; background:#e6ebf4; border-radius:2px; }
QSlider::sub-page:horizontal { background:#86a1ef; border-radius:2px; }
QSlider::handle:horizontal { background:#3b61e9; border:2px solid white; width:12px; height:12px; margin:-6px 0; border-radius:8px; }
QSlider::handle:horizontal:hover { background:#234bd6; }
QTabWidget::pane { border:0; background:transparent; }
QTabBar::tab { background:#f3f5f9; color:#7b89a0; border:0; border-radius:7px; margin:2px 3px 10px 0; padding:9px 18px; }
QTabBar::tab:selected { background:#e9efff; color:#365bd5; font-weight:600; }
QTabBar::tab:hover:!selected { background:#edf1f8; color:#526987; }
QScrollBar:vertical { background:transparent; width:8px; margin:2px 0; }
QScrollBar::handle:vertical { background:#d5deeb; min-height:32px; border-radius:4px; }
QScrollBar::handle:vertical:hover { background:#b9c8dc; }
QScrollBar:horizontal { background:transparent; height:8px; margin:0 2px; }
QScrollBar::handle:horizontal { background:#d5deeb; min-width:32px; border-radius:4px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; border:0; background:transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QPlainTextEdit { border:1px solid #e1e7f0; border-radius:10px; background:#fafbfe; padding:12px; selection-background-color:#dfe8ff; }
QTableWidget { background:white; alternate-background-color:#f7f9fd; border:1px solid #e1e7f0; border-radius:10px; gridline-color:#edf1f7; selection-background-color:#e9efff; selection-color:#2549b8; }
QHeaderView::section { background:#f4f7fc; color:#6b7d97; border:0; border-bottom:1px solid #e1e7f0; padding:10px 12px; font-weight:600; }
QToolTip { background:#24364f; color:white; border:0; border-radius:6px; padding:7px 10px; }
'''.replace('__ASSETS__',_ASSETS)
