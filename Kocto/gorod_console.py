"""Точка входа для сборки GorodPomnit-console.exe. Из исходников: python gorod_console.py"""
import sys

if '--legacy' in sys.argv:
    from gorod.console import main
else:
    from gorod.god.console import main

if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):  # кириллица в любой консоли Windows
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
