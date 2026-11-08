from pathlib import Path
import sys


def resource_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def portable_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else resource_dir()


def data_dir() -> Path:
    path = portable_dir() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path
