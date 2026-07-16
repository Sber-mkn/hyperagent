import pathlib
import sys

from PyQt6.QtWidgets import QApplication

from client.ui.qt import HyperagentClientWindow

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = HyperagentClientWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
