"""Frozen/UI smoke checks for god mode: real widgets, clipboard, world, TCP."""
from __future__ import annotations
import copy
import tempfile
import time
from pathlib import Path
from .ui import App
from .world import forecast,attraction,fingerprint
from .language import parse
from . import network as N
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
        app.entry.delete(0,'end');app.entry.insert(0,'Создать возможность встречи a0 и a999');app.prepare();assert not app.pending.ready and str(app.apply_btn['state'])=='disabled';app.cancel()
        app.advance(104);assert app.world.state['week']==13 and app.world.state['elections']
        app.tabs.select(app.frames['crises']);rows=app.crisis_tree.get_children();assert rows
        app.crisis_tree.selection_set(rows[0]);app.crisis_details();assert 'Мандат:' in app.crisis_text.get('1.0','end')
        assert any(r['assembly']['members'] for r in app.world.state['crises']['items'])
        app.tabs.select(app.frames['homes']);app.homes.selection_set('c0');app.household_details()
        assert app.world.state['cohorts'][0]['household']['ledger'] and 'Денежный журнал' in app.home_text.get('1.0','end')
        app.refresh();assert app.homes.selection()==('c0',) and 'Денежный журнал' in app.home_text.get('1.0','end')
        app.tabs.select(app.frames['actors']);app.actors.selection_set('a0');app.actor_details()
        assert app.world.state['actors']['a0']['decision']['options'] and 'Знания политика' in app.actor_text.get('1.0','end')
        app.tabs.select(app.frames['civic']);app.civic_views['institutions'].selection_set('factory:clinic');app.civic_details_show('institutions')
        assert 'Спрос' in app.civic_details['institutions'].get('1.0','end')
        assert len(app.world.state['civic']['institutions'])==12 and app.world.state['civic']['documents']
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
            old=copy.deepcopy(World(seed=87).state);old.pop('territory',None);old.pop('crises',None);old.pop('story',None);old['schema']=1;old.pop('territory',None);old.pop('crises',None);old.pop('story',None);old.pop('civic')
            for c in old['cohorts']:del c['household'];del c['life'];del c['service_pressure'];del c['service_cause']
            for a in old['actors'].values():del a['decision']
            for p in old['parties'].values():del p['intel'];del p['intent']
            from .world import previous_data
            data=previous_data(app.world.data,1)
            payload={'format':'god-world','schema':1,'rules':fingerprint(data),'state':old}
            legacy_path=Path(tmp)/'сейв080.json';legacy_path.write_text(json.dumps({'payload':payload,'checksum':fingerprint(payload)},ensure_ascii=False),encoding='utf-8')
            same.load(legacy_path);assert same.migration_notice and same.state['week']==old['week']
            same.step()
        app.world=World(seed=87,scenario='last_winter');app.refresh();assert 'ПОСЛЕДНЯЯ ЗИМА' in app.story_text.get('1.0','end')
        app.world.step(26,False);app.refresh();assert app.world.state['story']['finished'] and str(app.continue_btn['state'])=='normal'
        app.continue_story();app.world.step();assert app.world.state['week']==28
        app.world=World(seed=87,scenario='last_winter');app.refresh()
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
        guest.dispatch('story',{'op':'goal','value':'ties'});pump_until(lambda:not guest.net_busy)
        assert guest.world.state==app.world.state and app.world.state['story']['goal']=='ties'
        guest.dispatch('plan','Усилить внимание к экологии');pump_until(lambda:not guest.net_busy)
        assert guest.world.state==app.world.state
        guest.dispatch('step',1);pump_until(lambda:not guest.net_busy)
        assert guest.world.state==app.world.state
        app.world=World(seed=87,scale='federation');app.refresh();app.link.send({'type':'god-state','snapshot':N.snapshot(app.world)})
        pump_until(lambda:guest.world.state['territory'] is not None)
        guest.dispatch('territory',{'op':'select','value':'r1:c0'});pump_until(lambda:not guest.net_busy)
        assert app.world.state==guest.world.state and app.world.state['territory']['active']=='r1:c0'
        guest.dispatch('step',1);pump_until(lambda:not guest.net_busy);assert app.world.state==guest.world.state
        guest.world.state['budget']+=.25 # deliberate divergence: verify full resync, no command replay
        app.dispatch('territory',{'op':'boundary','value':{'metric':'health','floor':65}})
        pump_until(lambda:app.world.state==guest.world.state)
        assert guest.world.state['crises']['boundary']['floor']==65
        return {'crisis_ui':True,'network_delta_resync':True,'god_ui':True,'god_world':True,'god_clipboard':True,'god_shortcuts':True,'god_save':True,'god_tcp':True,'households':True,'agent_planner':True,'migration_080':True,'institutions':True,'civic_projects':True,'document_ui':True,'scenario_ui':True,'scenario_epilogue':True,'scenario_tcp':True,'federation_ui':True,'federation_tcp':True}
    finally:
        if guest:guest.close()
        app.close()
