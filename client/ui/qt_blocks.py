from typing import override

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)


class PaperPlaneButton(QPushButton):
    def __init__(self) -> None:
        super().__init__("")
        self.setObjectName("sendButton")

    @override
    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = QColor("#616671") if not self.isEnabled() else QColor("#dfe6f5")
        if self.isEnabled() and self.underMouse():
            color = QColor("#f2f6ff")

        side = min(self.width(), self.height()) * 0.58
        left = (self.width() - side) / 2
        top = (self.height() - side) / 2

        def point(x: float, y: float) -> QPointF:
            return QPointF(left + side * x, top + side * y)

        path = QPainterPath(point(0.06, 0.08))
        path.lineTo(point(0.94, 0.50))
        path.lineTo(point(0.06, 0.92))
        path.lineTo(point(0.22, 0.58))
        path.lineTo(point(0.58, 0.50))
        path.lineTo(point(0.22, 0.42))
        path.closeSubpath()

        painter.setPen(QPen(color, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class CollapsibleBlock(QFrame):
    def __init__(self, title: str, expanded: bool = True) -> None:
        super().__init__()
        self.setObjectName("collapsibleBlock")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.header_button = QToolButton()
        self.header_button.setObjectName("collapsibleHeader")
        self.header_button.setText(title)
        self.header_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header_button.setAutoRaise(True)
        self.header_button.setCheckable(True)
        self.header_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_button.clicked.connect(self.toggle)

        self.body_frame = QFrame()
        self.body_frame.setObjectName("collapsibleBody")
        self.body_layout = QVBoxLayout(self.body_frame)
        self.body_layout.setContentsMargins(14, 6, 10, 8)
        self.body_layout.setSpacing(6)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.header_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.body_frame)

        self.set_expanded(expanded)

    def toggle(self) -> None:
        self.set_expanded(not self.body_frame.isVisible())

    def set_expanded(self, expanded: bool) -> None:
        self.header_button.setChecked(expanded)
        self.header_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.body_frame.setVisible(expanded)

    def collapse(self) -> None:
        self.set_expanded(False)


class StreamTextBlock(CollapsibleBlock):
    def __init__(self, title: str, text_object_name: str, expanded: bool = True) -> None:
        super().__init__(title, expanded)
        self._text = ""
        self.text_label = QLabel("")
        self.text_label.setObjectName(text_object_name)
        self.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body_layout.addWidget(self.text_label)

    def append_text(self, text: str) -> None:
        self._text += text
        self.text_label.setText(self._text)


class CommandBlock(QFrame):
    _waiting_frames = ("Waiting", "Waiting.", "Waiting..", "Waiting...")

    def __init__(self, command_id: str, command: str, cwd: str = "") -> None:
        super().__init__()
        self.command_id = command_id
        self._waiting_index = 0

        self.setObjectName("commandBlock")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        icon_label = QLabel(">_")
        icon_label.setObjectName("commandIcon")

        title_label = QLabel("Run command")
        title_label.setObjectName("commandTitle")

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(9)
        header_layout.addWidget(icon_label)
        header_layout.addWidget(title_label, 1)

        self.command_label = QLabel(command)
        self.command_label.setObjectName("commandText")
        self.command_label.setTextFormat(Qt.TextFormat.PlainText)
        self.command_label.setWordWrap(True)
        self.command_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.status_label = QLabel(self._waiting_frames[0])
        self.status_label.setObjectName("commandWaiting")

        self.details_block = CollapsibleBlock("Подробнее", expanded=False)
        self.details_block.setObjectName("commandDetails")
        self.details_label = QLabel(self._format_details(command, cwd, None))
        self.details_label.setObjectName("commandDetailsText")
        self.details_label.setTextFormat(Qt.TextFormat.PlainText)
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details_block.body_layout.addWidget(self.details_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(12)
        layout.addLayout(header_layout)
        layout.addWidget(self.command_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.details_block)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(350)

    def complete(self, result: dict) -> None:
        self._timer.stop()
        returncode = result.get("returncode")
        if returncode == 0:
            self.status_label.setObjectName("commandDone")
            self.status_label.setText("✓ Done")
        else:
            self.status_label.setObjectName("commandFailed")
            self.status_label.setText("x Failed")
        self.details_label.setText(
            self._format_details(
                str(result.get("command") or self.command_label.text()),
                str(result.get("cwd") or ""),
                result,
            )
        )
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _tick(self) -> None:
        self._waiting_index = (self._waiting_index + 1) % len(self._waiting_frames)
        self.status_label.setText(self._waiting_frames[self._waiting_index])

    @staticmethod
    def _format_details(command: str, cwd: str, result: dict | None) -> str:
        lines = [f"command: {command}"]
        if cwd:
            lines.append(f"cwd: {cwd}")
        if result is None:
            lines.append("returncode: pending")
            return "\n".join(lines)

        lines.append(f"returncode: {result.get('returncode')}")
        lines.append("")
        lines.append("stdout:")
        lines.append(str(result.get("stdout") or ""))
        lines.append("")
        lines.append("stderr:")
        lines.append(str(result.get("stderr") or ""))
        return "\n".join(lines)


class CommandGroupBlock(CollapsibleBlock):
    def __init__(self) -> None:
        super().__init__("Выполняет:", expanded=True)
        self._commands: dict[str, CommandBlock] = {}

    def add_command(self, command_id: str, command: str, cwd: str) -> CommandBlock:
        block = CommandBlock(command_id, command, cwd)
        self._commands[command_id] = block
        self.body_layout.addWidget(block)
        return block

    def command(self, command_id: str) -> CommandBlock | None:
        return self._commands.get(command_id)
