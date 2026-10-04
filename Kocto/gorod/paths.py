"""Где лежат сохранения: рядом с GorodPomnit.exe в сборке, в папке Kocto при запуске из исходников."""
from __future__ import annotations

import sys
from pathlib import Path


def save_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller: __file__ указывает во временную папку
        return Path(sys.executable).resolve().parent / "gorod_saves"
    return Path(__file__).resolve().parent.parent / "gorod_saves"
