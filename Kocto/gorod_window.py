"""Точка входа Windows-сборки; --smoke-test-ui только для CI."""
import sys

if __name__ == '__main__':
    if '--diagnose-graphics' in sys.argv:
        from gorod import graphics as G
        from pathlib import Path
        import json, platform
        target = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
        (target/'graphics-diagnostic.txt').write_text(json.dumps({**G.diagnostic(), 'os': platform.platform()}, ensure_ascii=False, indent=2), encoding='utf-8')
        sys.exit(0)
    if '--smoke-test-ui' in sys.argv:
        from gorod.smoke_ui import run
        sys.exit(run())
    if '--legacy' in sys.argv:
        from gorod.ui_tk import main
    else:
        from gorod.god.ui import main
    main()
