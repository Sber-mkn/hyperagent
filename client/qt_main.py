import argparse
import pathlib
import sys

from PyQt6.QtWidgets import QApplication

from client.ui.qt import HyperagentClientWindow

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=pathlib.Path, default=None)
    return parser.parse_known_args(argv)


def main() -> None:
    args, qt_args = _parse_args(sys.argv[1:])
    app = QApplication([sys.argv[0], *qt_args])
    app.setStyle("Fusion")
    window = HyperagentClientWindow(data_dir=args.data)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
