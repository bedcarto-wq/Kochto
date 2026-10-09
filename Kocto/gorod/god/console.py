"""Text-only god simulation. No Pillow/Tk dependency, stdlib only."""
from pathlib import Path
from ..engine import RuleError,DataError
from ..paths import save_dir
from .world import World
from .language import parse,execute

def main():
    w=World(seed=87)
    print('Город помнит 0.8.1 · игрок — бог. Мир живёт сам.\nКоманды: статус, неделя, месяц, выборы, хроника, сохранить ИМЯ, загрузить ИМЯ, выход.\nНапишите вмешательство; выполнение только после подтверждения.')
    while True:
        try:text=input('Бог > ').strip()
        except EOFError:return 0
        try:
            if text in ('выход','exit'):return 0
            if text=='статус':print(w.summary())
            elif text in ('неделя','месяц','выборы'):
                reports=w.step({'неделя':1,'месяц':4,'выборы':104}[text],True)
                for report in reports:
                    for e in report['events']:print('#'+str(e['id'])+' '+e['text'])
                print(w.summary())
            elif text=='хроника':
                for e in w.state['events'][-20:]:print('#'+str(e['id'])+' / '+str(e['week'])+' / '+e['text'])
            elif text.startswith(('сохранить ','загрузить ')):
                verb,name=text.split(' ',1)
                if '/' in name or '\\' in name or name in ('.','..') or len(name)>80:raise RuleError('Только имя, без пути')
                path=save_dir()/(name if name.endswith('.json') else name+'.json')
                (w.save if verb=='сохранить' else w.load)(path);print('Готово:',path.name)
                if verb=='загрузить' and w.migration_notice:print(w.migration_notice)
            elif text:
                plan=parse(w,text);print(plan.record())
                if plan.ready and input('Применить за '+str(plan.cost)+' влияния? да/нет > ').strip().lower()=='да':execute(w,plan);print('Обстоятельства изменены. Люди выберут реакцию сами.')
        except (RuleError,DataError) as exc:print('Не выполнено:',str(exc))
