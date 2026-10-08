"""CI-only smoke check for frozen Windows UI, art and P2P protocol."""
from __future__ import annotations
import json
import sys
from pathlib import Path


def run():
    from .ui_tk import App
    from . import graphics as G
    from .multiplayer import Match, candidate
    from .p2p import Link, new_code
    from .multiplayer import fingerprint
    import time
    # Skip interactive candidate dialog but instantiate the real layout.
    original = App.new_game
    App.new_game = lambda self: None
    app = None
    host = guest = None
    try:
        app = App()
        skills = {'charm': 30, 'eloquence': 30, 'cunning': 30}
        app.session.new('Проверка', 'm', skills, seed=12)
        app.refresh()
        app.update()
        if not G.AVAILABLE or app.graphic_error:
            raise RuntimeError('Pillow / graphics failure: '+str(app.graphic_error))
        assert G.city(600, 320).width > 0
        assert G.portrait(0, 80).width == 80
        paper = G.newspaper([], 0)
        assert paper.height > 0
        m = Match(app.base_data, [candidate('Первый', 'm', skills), candidate('Вторая', 'f', skills)], seed=11)
        m.command(0, 0, 'ready'); m.command(1, 1, 'ready')
        assert m.states[0].week == 2
        host, guest = Link(), Link()
        code, rules = new_code(), fingerprint(app.base_data)
        host.host(code, rules, port=0, bind='127.0.0.1')
        port = host.events.get(timeout=5)['port']
        guest.join('127.0.0.1', code, rules, candidate('Вторая', 'f', skills), port)
        assert host.events.get(timeout=5)['type'] == 'connected'
        assert guest.events.get(timeout=5)['type'] == 'connected'
        host.send({'type': 'state', 'match': m.snapshot()})
        snapshot = guest.events.get(timeout=5)['match']
        assert Match.restore(app.base_data, snapshot).states[1].week == 2
        target = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
        (target/'ui-smoke-ok.json').write_text(json.dumps({'ui': True, 'pillow': True, 'p2p': True}), encoding='utf-8')
        return 0
    except Exception:
        import traceback
        target = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
        (target/'ui-smoke-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        return 1
    finally:
        App.new_game = original
        for link in (host, guest):
            if link:
                link.close()
        if app:
            app.close_app()
