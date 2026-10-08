"""Точка входа Windows-сборки; --smoke-test-ui только для CI."""
import sys

if __name__ == '__main__':
    if '--smoke-test-ui' in sys.argv:
        from gorod.smoke_ui import run
        sys.exit(run())
    from gorod.ui_tk import main
    main()
