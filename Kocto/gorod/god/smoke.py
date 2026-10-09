"""Frozen/UI smoke checks for god mode: real widgets, clipboard, world, TCP."""
from __future__ import annotations
import copy
import tempfile
import time
from pathlib import Path
from .ui import App
from .world import forecast,attraction,fingerprint
from .language import parse
from ..shortcuts import ShortcutStore
from ..p2p import Link,new_code


def run_checks():
    app=App(seed=87);guest=None
    try:
        app.update()
        assert app.world.summary()['population']==24000
        before=copy.deepcopy(app.world.state)
        app.clipboard_clear();app.clipboard_append('Усилить внимание рабочих к экологии')
        app.entry.event_generate('<<Paste>>');app.update();assert app.entry.get()=='Усилить внимание рабочих к экологии'
        app.prepare();assert app.pending.ready and app.world.state==before
        app.apply();assert app.world.state['energy']<100 and not app.world.state['editor_used']
        app.advance(104);assert app.world.state['week']==13 and app.world.state['elections']
        app.tabs.select(app.frames['homes']);app.homes.selection_set('c0');app.household_details()
        assert app.world.state['cohorts'][0]['household']['ledger'] and 'Денежный журнал' in app.home_text.get('1.0','end')
        app.refresh();assert app.homes.selection()==('c0',) and 'Денежный журнал' in app.home_text.get('1.0','end')
        app.tabs.select(app.frames['actors']);app.actors.selection_set('a0');app.actor_details()
        assert app.world.state['actors']['a0']['decision']['options'] and 'Знания политика' in app.actor_text.get('1.0','end')
        pop=app.world.summary()['population'];app.world.direct({'op':'popularity','party':'civic','value':20});assert app.world.state['editor_used']
        app.world.direct({'op':'dissolve','party':'order'});assert app.world.summary()['population']==pop and 'order' not in forecast(app.world.state)['shares']
        app.world.undo();app.world.undo();app.refresh()
        with tempfile.TemporaryDirectory() as tmp:
            app.shortcuts=ShortcutStore(Path(tmp)/'my.json');x=app.shortcuts.put('Экология','Усилить внимание к экологии');app.refresh_shortcuts()
            before=app.world.state['energy'];app.custom_inner.winfo_children()[0].invoke();assert app.pending.ready and app.world.state['energy']==before
            path=Path(tmp)/'мир.json';app.world.save(path)
            from .world import World
            same=World(seed=1);same.load(path);assert same.state==app.world.state
            # Prior schema, with exact shipped 0.8.0 rules. No invented history.
            import json
            old=copy.deepcopy(app.world.state);old['schema']=1
            for c in old['cohorts']:del c['household'];del c['life']
            for a in old['actors'].values():del a['decision']
            for p in old['parties'].values():del p['intel'];del p['intent']
            data=copy.deepcopy(app.world.data);data.pop('living');data['schema']=1
            payload={'format':'god-world','schema':1,'rules':fingerprint(data),'state':old}
            legacy_path=Path(tmp)/'сейв080.json';legacy_path.write_text(json.dumps({'payload':payload,'checksum':fingerprint(payload)},ensure_ascii=False),encoding='utf-8')
            same.load(legacy_path);assert same.migration_notice and same.state['week']==old['week']
            same.step()
        guest=App(seed=42);guest.withdraw()
        code=new_code();rules=fingerprint(app.world.data)
        app.link=Link();app.net_host=True;app.link.host(code,rules,port=0,bind='127.0.0.1')
        listen=app.link.events.get(timeout=5);assert listen['type']=='listening'
        guest.link=Link();guest.net_host=False;guest.link.join('127.0.0.1',code,rules,{'observer':'god'},listen['port'])
        def pump_until(condition):
            limit=time.monotonic()+8
            while time.monotonic()<limit:
                app.update();guest.update();time.sleep(.03)
                if condition():return
            raise AssertionError('God TCP timeout')
        pump_until(lambda:app.net_connected and guest.net_connected)
        assert guest.world.state==app.world.state
        guest.dispatch('plan','Усилить внимание к экологии');pump_until(lambda:not guest.net_busy)
        assert guest.world.state==app.world.state
        guest.dispatch('step',1);pump_until(lambda:not guest.net_busy)
        assert guest.world.state==app.world.state
        return {'god_ui':True,'god_world':True,'god_clipboard':True,'god_shortcuts':True,'god_save':True,'god_tcp':True,'households':True,'agent_planner':True,'migration_080':True}
    finally:
        if guest:guest.close()
        app.close()
