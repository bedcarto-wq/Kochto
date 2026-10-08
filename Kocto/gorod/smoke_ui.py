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
    import tempfile
    from .shortcuts import ShortcutStore
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
            raise RuntimeError('Pillow / graphics failure: '+str(app.graphic_error)+'\n'+str(G.IMPORT_ERROR))
        assert G.city(600, 320).width > 0
        assert G.portrait(0, 80).width == 80
        paper = G.newspaper([], 0)
        assert paper.height > 0
        assert app.session.data['_nlu'].__class__.__name__ == 'NeuralClassifier'
        state_before = app.session.state.actions_left
        app.entry.delete(0, 'end')
        app.clipboard_clear();app.clipboard_append('посидеть с бабушками на лавочке')
        app.entry.event_generate('<<Paste>>');app.update()
        assert app.entry.get() == 'посидеть с бабушками на лавочке'
        app.understand();assert app.session.view()['source'] == 'ИИ' and app.session.view()['ready']
        app.entry.selection_range(0,'end');app.clipboard_clear();app.clipboard_append('нанять охрану')
        app.entry.focus_force();app.update();app.entry.event_generate('<Control-KeyPress-v>');app.update()
        assert app.entry.get() == 'нанять охрану' and app.session.pending is None
        assert app.session.state.actions_left == state_before
        with tempfile.TemporaryDirectory() as tmp:
            app.shortcuts = ShortcutStore(Path(tmp)/'my_actions.json')
            shortcut = app.shortcuts.put('Штаб и охрана', 'Встретиться с рабочими; затем нанять охрану')
            app.refresh_shortcuts(shortcut['id'])
            app.custom_inner.winfo_children()[0].invoke();app.update()
            assert len(app.session.intent.steps)==2 and app.session.state.actions_left==state_before
            assert ShortcutStore(Path(tmp)/'my_actions.json').items[0]['name']=='Штаб и охрана'
        semantic = app.session.understand('Встретиться с рабочими; затем нанять охрану')
        assert semantic['ready'] and len(semantic['steps']) == 2
        app.session.confirm()
        app.refresh()
        assert app.session.state.actions_left == 1
        denied = app.session.understand('Не обещаю заморозить тарифы')
        assert not denied['ready']
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
        (target/'ui-smoke-ok.json').write_text(json.dumps({'ui': True, 'pillow': True, 'p2p': True, 'neural': True, 'clipboard': True, 'shortcuts': True}), encoding='utf-8')
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
