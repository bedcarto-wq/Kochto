"""God-view UI. No candidate, no omnipotent-party score hidden in indirect powers."""
from __future__ import annotations
import copy
import json
import platform
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog,messagebox
from .. import __version__, graphics as G
from ..engine import RuleError,DataError
from ..paths import save_dir
from ..shortcuts import ShortcutStore,normalize_clipboard
from .world import World,forecast,attraction,affected
from .language import parse,execute
from . import network as N
from . import living,agents,civic,story,territories,crises,crisis_life,upper_politics
from ..p2p import Link, NetworkError, new_code, DEFAULT_PORT
from .world import fingerprint
import queue

if G.AVAILABLE:from PIL import ImageTk


class App(tk.Tk):
    def __init__(self,seed=None,scenario=None,goal='livelihood',scale='city'):
        super().__init__();self.title('Кочто — Город помнит '+__version__+' · Бог и город')
        self.geometry('1280x900');self.minsize(1000,700)
        self.tk.call('tk','scaling',1.33333)
        self.world=World(seed,scenario=scenario,goal=goal,scale=scale);self.pending=None;self.running=False;self.speed=tk.StringVar(value='1 неделя / сек');self.last_error=''
        self.link=None;self.net_host=False;self.net_connected=False;self.net_busy=False;self.net_failed=False
        self.shortcuts=ShortcutStore(save_dir()/'god_actions.json');self.photo=None;self.legacy_window=None
        self._build();self.refresh();self.after(1000,self._clock);self.after(100,self.poll_network);self.protocol('WM_DELETE_WINDOW',self.close)
        if self.shortcuts.load_error:self.after(0,lambda:messagebox.showwarning('Мои силы',self.shortcuts.load_error,parent=self))

    def _button(self,parent,label,command,side='left'):
        b=ttk.Button(parent,text=label,command=command);b.pack(side=side,padx=3);return b

    def _text(self,parent,height=5):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True,padx=8,pady=4)
        scroll=ttk.Scrollbar(frame);scroll.pack(side='right',fill='y')
        text=tk.Text(frame,height=height,wrap='word',font=('Arial',11),yscrollcommand=scroll.set);text.pack(fill='both',expand=True);scroll.configure(command=text.yview)
        return text

    def _tree(self,parent,columns,height=8):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True,padx=8,pady=4)
        horizontal=ttk.Scrollbar(frame,orient='horizontal');horizontal.pack(side='bottom',fill='x')
        scroll=ttk.Scrollbar(frame);scroll.pack(side='right',fill='y')
        t=ttk.Treeview(frame,columns=[k for k,_ in columns],show='headings',height=height,yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        horizontal.configure(command=t.xview)
        for key,name in columns:t.heading(key,text=name);t.column(key,width=115,minwidth=55,anchor='w')
        t.pack(fill='both',expand=True);scroll.configure(command=t.yview);return t

    def _build(self):
        style=ttk.Style(self);style.configure('Treeview',rowheight=25,font=('Arial',10));style.configure('Treeview.Heading',font=('Arial',10,'bold'))
        top=ttk.Frame(self);top.pack(fill='x',padx=8,pady=6)
        for label,cmd in [('Новый мир',self.new_world),('Сохранить',self.save),('Загрузить',self.load),('Прямое управление',self.direct_menu),('Откат прямого',self.undo),('Отчёт',self.error_report)]:self._button(top,label,cmd)
        self._button(top,'P2P: два бога',self.network_menu)
        self._button(top,'Режим кандидата',self.legacy)
        timebar=ttk.Frame(self);timebar.pack(fill='x',padx=8,pady=4)
        self.run_btn=self._button(timebar,'▶ Наблюдать',self.toggle)
        for label,n in [('Неделя',1),('Месяц',4),('До выборов',104)]:self._button(timebar,label,lambda weeks=n:self.advance(weeks))
        ttk.Combobox(timebar,state='readonly',textvariable=self.speed,values=['1 неделя / сек','4 недели / сек'],width=18).pack(side='left',padx=6)
        self.header=ttk.Label(timebar,font=('Arial',11,'bold'));self.header.pack(side='right',padx=6)
        self.status=ttk.Label(self,wraplength=1150);self.status.pack(fill='x',padx=12,pady=3);self.status.bind('<Configure>',lambda e:self.status.configure(wraplength=max(300,e.width-12)))
        bottom=ttk.Frame(self);bottom.pack(side='bottom',fill='x',padx=8,pady=6)
        inputrow=ttk.Frame(bottom);inputrow.pack(fill='x')
        ttk.Label(inputrow,text='Вмешательство:').pack(side='left',padx=4)
        self.entry=ttk.Entry(inputrow,font=('Arial',12));self.entry.pack(side='left',fill='x',expand=True,padx=4)
        self.entry.bind('<Return>',lambda e:self.prepare());self.entry.bind('<<Paste>>',self.paste);self.entry.bind('<Shift-Insert>',self.paste)
        self.entry.bind('<Control-KeyPress>',self._clipboard_key);self.entry.bind('<KeyRelease>',self.changed);self.entry.bind('<Button-3>',self.context)
        self._button(inputrow,'Вставить',self.paste);self._button(inputrow,'Понять',self.prepare)
        tools=ttk.Frame(bottom);tools.pack(fill='x',pady=4)
        self._button(tools,'Конструктор силы',self.power_menu);self._button(tools,'+ Моя сила',self.add_shortcut)
        self.shortcut_var=tk.StringVar();self.shortcut_box=ttk.Combobox(tools,state='readonly',textvariable=self.shortcut_var,width=24);self.shortcut_box.pack(side='left',padx=4)
        self._button(tools,'Подготовить',self.prepare_shortcut);self._button(tools,'Изменить / удалить',self.edit_shortcut)
        self._button(tools,'Объяснение',self.explain,side='right')
        self.custom_bar=ttk.Frame(bottom)
        self.custom_canvas=tk.Canvas(self.custom_bar,height=30,highlightthickness=0)
        self.custom_canvas.pack(fill='x')
        self.custom_inner=ttk.Frame(self.custom_canvas);self.custom_canvas.create_window(0,0,anchor='nw',window=self.custom_inner)
        self.custom_scroll=ttk.Scrollbar(self.custom_bar,orient='horizontal',command=self.custom_canvas.xview)
        self.custom_canvas.configure(xscrollcommand=self.custom_scroll.set)
        self.custom_inner.bind('<Configure>',lambda e:self._shortcut_scroll());self.custom_canvas.bind('<Configure>',lambda e:self._shortcut_scroll())
        self.refresh_shortcuts()
        self.preview=ttk.LabelFrame(bottom,text='Предварительный разбор — ничего не выполнено');self.preview.pack(fill='x',pady=4)
        self.preview_text=ttk.Label(self.preview,text='Пример: Усилить внимание рабочих к экологии; затем улучшить транспорт в Заречье',wraplength=1150,justify='left');self.preview_text.pack(fill='x',padx=8,pady=4);self.preview.bind('<Configure>',lambda e:self.preview_text.configure(wraplength=max(300,e.width-24)))
        buttons=ttk.Frame(self.preview);buttons.pack(fill='x',padx=6,pady=4)
        self.apply_btn=self._button(buttons,'Применить вмешательство',self.apply);self.apply_btn.configure(state='disabled')
        self._button(buttons,'Отмена',self.cancel)
        self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True,padx=8,pady=4)
        frames={}
        for key,label in [('world','Масштаб'),('story','История'),('crises','Кризисы'),('city','Город'),('people','Избиратели'),('homes','Быт'),('civic','Общество'),('parties','Политика'),('history','Хроника'),('election','Выборы'),('actors','Люди'),('limits','План')]:
            frames[key]=ttk.Frame(self.tabs);self.tabs.add(frames[key],text=label)
        self.frames=frames
        self.world_tree=self._tree(frames['world'],[('name','Город / область'),('population','Жители'),('jobs','Занятость'),('income','Доход'),('pressure','Кризисы')],height=5)
        self.world_tree.column('name',width=260,minwidth=200)
        wt=ttk.Frame(frames['world']);wt.pack(fill='x',padx=8,pady=4);self._button(wt,'Открыть выбранный город',self.select_city);self._button(wt,'Верхние партии',self.upper_menu)
        self.world_text=self._text(frames['world'],9)
        self.crisis_tree=self._tree(frames['crises'],[('id','ID'),('kind','Кризис'),('stage','Стадия'),('material','Тяжесть'),('capacity','Способность'),('division','Раскол')],height=5)
        self.crisis_tree.column('kind',width=230,minwidth=170);self.crisis_tree.column('stage',width=210,minwidth=180)
        self.crisis_tree.bind('<<TreeviewSelect>>',self.crisis_details)
        ct=ttk.Frame(frames['crises']);ct.pack(fill='x',padx=8,pady=4)
        self.crisis_goal=ttk.Combobox(ct,state='readonly',values=list(crises.GOALS.values()),width=48);self.crisis_goal.pack(side='left');self.crisis_goal.current(0)
        self._button(ct,'Принять обязательство',self.choose_crisis_goal)
        self._button(ct,'Граница потерь',self.crisis_boundary)
        self.crisis_text=self._text(frames['crises'],8)
        storytools=ttk.Frame(frames['story']);storytools.pack(fill='x',padx=8,pady=6)
        self.goal_box=ttk.Combobox(storytools,state='readonly',values=list(story.GOALS.values()),width=48);self.goal_box.pack(side='left',padx=4);self.goal_box.current(0)
        self._button(storytools,'Пересмотреть обязательство',self.change_goal)
        self.continue_btn=self._button(storytools,'Продолжить мир',self.continue_story)
        self.story_text=self._text(frames['story'],18)
        city=ttk.Panedwindow(frames['city'],orient='horizontal');city.pack(fill='both',expand=True)
        imageframe=ttk.Frame(city);city.add(imageframe,weight=1)
        self.city_canvas=tk.Canvas(imageframe,bg='#f5f0e4',height=210,highlightthickness=0);self.city_canvas.pack(fill='both',expand=True,padx=6,pady=6);self.city_canvas.bind('<Configure>',lambda e:self.draw_city())
        self.city_caption=ttk.Label(imageframe,text='Условный вид города. Числа справа — реальные состояния районов.',wraplength=380);self.city_caption.pack(fill='x',padx=8,pady=4)
        right=ttk.Frame(city);city.add(right,weight=2)
        self.districts=self._tree(right,[('name','Район'),('pop','Жители'),('income','Доход'),('jobs','Занятость'),('infra','Инфра.'),('access','Доступ')],height=4)
        self.districts.column('name',width=180,minwidth=150)
        for key in ('pop','income','jobs','infra','access'):self.districts.column(key,width=70,minwidth=55)
        self.city_feed=self._text(right,6)
        filters=ttk.Frame(frames['people']);filters.pack(fill='x',padx=8,pady=6)
        ttk.Label(filters,text='Пересекающиеся признаки:').pack(side='left')
        self.filter=tk.StringVar(value='Все жители');self.filter_box=ttk.Combobox(filters,state='readonly',textvariable=self.filter,values=['Все жители']+list(self.world.data['tags'].values()),width=24);self.filter_box.pack(side='left',padx=6);self.filter_box.bind('<<ComboboxSelected>>',lambda e:self.refresh_people())
        self.filter2=tk.StringVar(value='Любой второй признак')
        filter2=ttk.Combobox(filters,state='readonly',textvariable=self.filter2,values=['Любой второй признак']+list(self.world.data['tags'].values()),width=24);filter2.pack(side='left',padx=4);filter2.bind('<<ComboboxSelected>>',lambda e:self.refresh_people())
        self.filter_count=ttk.Label(filters);self.filter_count.pack(side='left',padx=6)
        self.people=self._tree(frames['people'],[('id','Когорта'),('district','Район'),('tags','Признаки'),('pop','Жители'),('econ','Экономика'),('faith','Традиции'),('best','Первый выбор')])
        self.people.column('tags',width=260);self.people.bind('<<TreeviewSelect>>',self.cohort_details)
        self.details=self._text(frames['people'],5)
        ttk.Label(frames['homes'],text='Представительное домохозяйство когорты · условные рубли за неделю · не отдельные семьи и не реальные статистические данные',wraplength=940).pack(anchor='w',padx=8,pady=6)
        self.homes=self._tree(frames['homes'],[('id','Когорта'),('district','Район'),('income','Доход'),('needs','Нужды'),('balance','Баланс'),('savings','Резерв'),('debt','Долг'),('goal','Решение')],height=8)
        for key in ('id','income','needs','balance','savings','debt'):self.homes.column(key,width=90,minwidth=70)
        self.homes.column('district',width=175);self.homes.column('goal',width=200)
        self.homes.bind('<<TreeviewSelect>>',self.household_details);self.home_text=self._text(frames['homes'],8)
        self.parties=self._tree(frames['parties'],[('name','Партия'),('leader','Лидер'),('share','Прогноз %'),('seats','Места'),('org','Организация'),('funds','Ресурсы'),('axes','Экономика / свободы')],height=5)
        self.parties.column('name',width=210);self.parties.column('leader',width=150)
        self.political_text=self._text(frames['parties'],8)
        histbar=ttk.Frame(frames['history']);histbar.pack(fill='x',padx=8,pady=4)
        self._button(histbar,'Экспорт хроники TXT',self.export_history)
        self.history=self._tree(frames['history'],[('id','ID'),('week','Неделя'),('kind','Тип'),('text','Событие')],height=10);self.history.column('text',width=700);self.history.column('id',width=45);self.history.column('week',width=60);self.history.bind('<<TreeviewSelect>>',self.event_details)
        self.event_text=self._text(frames['history'],5)
        self.elections=self._text(frames['election'],16)
        self.actors=self._tree(frames['actors'],[('name','Персонаж'),('role','Роль'),('goal','Собственная цель'),('age','Возраст'),('status','Состояние')],height=8);self.actors.column('goal',width=300);self.actors.bind('<<TreeviewSelect>>',self.actor_details)
        self.actor_text=self._text(frames['actors'],5)
        sub=ttk.Notebook(frames['civic']);sub.pack(fill='both',expand=True)
        self.civic_views={};self.civic_details={}
        for key,label,cols in [('institutions','Учреждения',[('id','ID'),('name','Учреждение / район'),('capacity','Вместимость'),('staff','Персонал %'),('served','Обслужено'),('queue','Ожидание'),('delay','Задержка')]),
            ('projects','Проекты',[('id','ID'),('party','Партия'),('stage','Стадия'),('progress','Готовность %'),('spent','Расход'),('opening','Объявлено открытие')]),
            ('associations','Объединения',[('id','ID'),('district','Район'),('members','Участники'),('resources','Ресурсы'),('fatigue','Усталость'),('status','Состояние')]),
            ('documents','Документы',[('id','ID'),('project','Проект'),('kind','Документ'),('stage','Факт на дату'),('access','Доступ'),('published','Опубликован')])]:
            frame=ttk.Frame(sub);sub.add(frame,text=label);tree=self._tree(frame,cols,height=8);tree.column('id',width=100,minwidth=70)
            if key=='institutions':tree.column('name',width=260,minwidth=260)
            tree.bind('<<TreeviewSelect>>',lambda e,k=key:self.civic_details_show(k));self.civic_views[key]=tree;self.civic_details[key]=self._text(frame,6)
        frame=ttk.Frame(sub);sub.add(frame,text='Причины изменений');self.cause_text=self._text(frame,16)
        self.limits=self._text(frames['limits'],18)
        self._set(self.limits,'0.8.9 — самостоятельные верхние партийные отделения; собрания, мандаты, отказы, соглашения, реальные выплаты и восстановление кризисов; сценарий с обязательством и эпилогом; следующий слой рабочей основы новой концепции, не все 132 пункта в полном объёме.\n\nРаботают: автономные недели; 144 когорты с пересекающимися признаками; идеологическая близость и оценки каждой партии; отдельная явка; партии, агитация и смена программ; обещания и проекты; коалиции; три правила выборов; информация и известные факты; инфраструктура, занятость, миграция; движения и преемники; косвенные силы; прямой редактор; контрольная сумма сохранений.\n\nУпрощены: внутри когорт распределение описано средним и разбросом; проекты и хозяйство агрегированы; отношения индивидуальны только у ключевых лиц; журналистика и память событий имеют небольшое число правил.\n\nВ 0.8.5: учреждения имеют вместимость, персонал и очереди; жители создают объединения и оценивают ответы партий; проекты проходят согласование, финансирование, выполнение и набор персонала. Документы хранят факты на дату, журналист сопоставляет объявление и акт. Новые силы создают возможность встречи, доступ к документу, свободное время и облегчают координацию. Ни встреча, ни публикация, ни поддержка партии не гарантированы. Причинный архив ограничен; изменения привлекательности разложены по компонентам, но вклад каждого отдельного события не вычисляется.\n\nДобавлены: бюджеты представительных домохозяйств (расходы, резерв, кредит, проценты, нехватка); решения о работе, курсе, заботе и взаимопомощи. Политики сравнивают действия по стоимости, характеру и сохранённой выборке, а не читают точные предпочтения всех жителей. Это прозрачный планировщик, не нейросетевые личности.\n\nЕщё не готовы: отдельные индивидуальные домохозяйства, подробный жизненный план каждого гражданина, второй тур, объединение партий, индивидуальное обучение стратегий и отложенные условные чудеса. P2P бога — два доверенных наблюдателя/участника одного мира с авторитетным создателем.\n\nСвободный ввод не означает произвольный исполняемый код. Неподдерживаемая механика блокируется. Нейросеть предлагает варианты; условия и приказы не превращаются в готовую победу партии.\n\nНовый слой: участники собраний — существующие жители; мандаты избираются, предложения могут быть отвергнуты. Соглашения имеют сроки и стоимость; помощь идёт через обычный денежный журнал, обучение не мгновенно. P2P передаёт проверяемые дельты и восстанавливает полный снимок при расхождении. Не добавлены полная микропопуляция, полные карьеры федеральных политиков и внутриотделенческие выборы, защищённый транспорт, LOD и вся система из 50 кризисных предложений.\n\nПодробный план: ПЛАН_0_8.md и КРИЗИСЫ_50.md в репозитории.')

    def _set(self,widget,text):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',text);widget.configure(state='disabled')

    def clear(self,tree):tree.delete(*tree.get_children())

    def draw_city(self):
        if not G.AVAILABLE:self.city_canvas.delete('all');self.city_canvas.create_text(20,20,anchor='nw',text=G.unavailable_message(),width=max(100,self.city_canvas.winfo_width()-40));return
        try:
            width=max(100,self.city_canvas.winfo_width()-16);height=max(70,self.city_canvas.winfo_height()-16)
            self.photo=ImageTk.PhotoImage(G.city(width,height));self.city_canvas.delete('all');self.city_canvas.create_image(self.city_canvas.winfo_width()/2,self.city_canvas.winfo_height()/2,image=self.photo)
            self.city_caption.configure(wraplength=width)
        except Exception as exc:self.last_error=traceback.format_exc();self.city_caption.configure(text='Ошибка графики: '+str(exc))

    def cancel(self):
        self.pending=None;self.apply_btn.configure(state='disabled');self.preview_text.configure(text='Введите вмешательство или выберите силу. Результат выборов не назначается.')

    def target_name(self,target):
        names={'all':'Весь город',**self.world.data['tags'],**{k:v['name'] for k,v in self.world.data['districts'].items()}}
        import re
        return ''.join(names.get(p,p) if p not in ('&','|') else (' ∩ ' if p=='&' else ' ∪ ') for p in re.split(r'([&|])',target))

    def changed(self,event=None):
        if self.pending and self.entry.get().strip()!=self.pending.text.strip():self.cancel()

    def prepare(self):
        self.running=False;self.run_btn.configure(text='▶ Наблюдать')
        try:
            self.pending=parse(self.world,self.entry.get().strip());p=self.pending
            lines=[]
            for c in p.commands:
                topic=self.world.data['topics'].get(c['topic'],{}).get('name','без заданной темы')
                lines.append(self.world.data['powers'][c['power']]['name']+' · '+self.target_name(c['target'])+' · '+topic+' · сила '+str(c['strength'])+' · '+str(c['duration'])+' нед.')
                refs=[]
                for key in ('actor_a','actor_b','document_id','association_id'):
                    if c.get(key):refs.append(c[key]+(' · '+self.world.state['actors'].get(c[key],{}).get('name','неизвестный персонаж') if key.startswith('actor_') else ''))
                if refs:lines.append('Участники / объект: '+', '.join(refs))
            lines+=p.blocked
            if any(c['power'] in civic.NEW_POWERS for c in p.commands):lines.append('Меняется возможность: встреча, публикация и выбор жителей не гарантированы.')
            if p.ready:lines.append('Цена: '+str(p.cost)+' влияния. Будут изменены обстоятельства, не итог голосования.')
            self.preview_text.configure(text='\n'.join(lines) or 'Нет исполнимого вмешательства');self.apply_btn.configure(state='normal' if p.ready else 'disabled')
        except (RuleError,DataError) as exc:self.cancel();messagebox.showerror('Разбор',str(exc),parent=self)

    def apply(self):
        if not self.pending:return
        try:self.dispatch('plan',self.pending.text)
        except (RuleError,DataError) as exc:messagebox.showerror('Вмешательство',str(exc),parent=self);return
        self.cancel();self.refresh()

    def advance(self,weeks=1):
        self.cancel()
        try:
            if self.link:
                count=len(self.world.state['elections']);self.dispatch('step',weeks)
                if self.net_host and len(self.world.state['elections'])>count:self.running=False;self.run_btn.configure(text='▶ Наблюдать');self.tabs.select(self.frames['election'])
                self.refresh();return
            reports=self.world.step(weeks,True)
        except (RuleError,DataError) as exc:self.running=False;messagebox.showerror('Мир',str(exc),parent=self);return
        if any(r['election'] for r in reports):self.running=False;self.run_btn.configure(text='▶ Наблюдать');self.tabs.select(self.frames['election'])
        self.refresh()

    def toggle(self):
        self.cancel();self.running=not self.running;self.run_btn.configure(text='⏸ Пауза' if self.running else '▶ Наблюдать')

    def _clock(self):
        if self.running:self.advance(4 if self.speed.get().startswith('4') else 1)
        self.after(1000,self._clock)

    def refresh(self):
        selected={key:getattr(self,key).selection() for key in ('homes','actors','people','history')}
        s=self.world.state;v=self.world.summary()
        self.refresh_territories()
        if hasattr(self,'_upper_refresh'):self._upper_refresh()
        self._set(self.story_text,'\n\n'.join(story.briefing(s)))
        self.continue_btn.configure(state='normal' if s['story'] and s['story']['finished'] and not s['story']['continued'] else 'disabled')
        if s['story']:self.goal_box.current(list(story.GOALS).index(s['story']['goal']))
        if s['story'] and s['story']['finished'] and not s['story']['continued']:
            self.running=False;self.run_btn.configure(text='▶ Наблюдать');self.tabs.select(self.frames['story'])
        self.header.configure(text='Неделя '+str(v['week'])+' · влияние '+str(round(v['energy']))+'/100')
        self.status.configure(text=('Масштаб: '+territories.SCALES[s['territory']['scale']]+' · выбран '+s['territory']['meta'][s['territory']['active']]['name']+' · всего '+str(sum(c['population'] for city in territories.cities(s).values() for c in city['cohorts']))+' жителей · ' if s['territory'] else 'Масштаб: город · ')+str(v['population'])+' избирателей · '+str(v['cohorts'])+' когорт · выборы: неделя '+str(v['next_election'])+' · власть: '+(', '.join(v['government']) or 'вакантна')+(' · использован прямой редактор' if v['editor_used'] else ' · косвенное управление')+(' · P2P: '+('создатель' if self.net_host else 'друг') if self.link else ''))
        self.clear(self.districts)
        for did,d in s['districts'].items():self.districts.insert('', 'end',iid=did,values=(d['name'],d['population'],round(d['income']),round(d['jobs']),round(d['infra']),round(d['access'])))
        self._set(self.city_feed,('НЕДЕЛЬНАЯ СВОДКА\n\n'+'\n\n'.join(s['story']['weekly'] if s['story'] else s['crises']['summary'])+'\n\n')+'ПОСЛЕДНИЕ СОБЫТИЯ\n\n'+'\n\n'.join('Неделя '+str(e['week'])+' · '+e['text'] for e in s['events'][-5:]))
        self.refresh_people();self.clear(self.homes)
        for c in s['cohorts']:
            h=c['household'];self.homes.insert('','end',iid=c['id'],values=(c['id'],s['districts'][c['district']]['name'],round(h['income']),round(h['needs']),round(h['balance']),round(h['savings']),round(h['debt']),living.ACTIONS[c['life']['action']]))
        self.clear(self.parties)
        last=s['elections'][-1] if s['elections'] else {'seats':{}}
        for pid,p in s['parties'].items():
            if p['active']:self.parties.insert('', 'end',iid=pid,values=(p['name'],s['actors'][p['leader']]['name'],round(v['forecast']['shares'].get(pid,0),1),last['seats'].get(pid,'—'),round(p['organization']),round(p['funds']),str(round(p['ideology']['economy']))+' / '+str(round(p['ideology']['freedom']))))
        promise_status={'open':'в силе','kept':'выполнено','partial':'частично','broken':'сорвано','cancelled':'отменено'}
        promises=[s['parties'][x['party']]['name']+' / '+s['districts'][x['district']]['name']+' / '+self.world.data['topics'][x['topic']]['name']+' · '+promise_status.get(x['status'],x['status'])+' · до недели '+str(x['deadline']) for x in s['promises'][-12:]]
        firms=['Предприятие: '+f['name']+' · работников '+str(f['workers'])+' · капитал '+str(round(f['capital'])) for f in s['firms'].values()]
        self._set(self.political_text,'Прогноз наблюдателя — не знания агента. Политики выбирают действия по своей неполной выборке.\nОценочная явка: '+str(round(v['forecast']['turnout'],1))+'%.\nБюджет города: '+str(round(s['budget']))+'; незавершённых проектов: '+str(sum(p['stage'] not in ('operating','rejected') for p in s['projects']))+'; общественных движений: '+str(sum(m['active'] for m in s['movements']))+'\n'+'\n'.join(firms)+'\n\nОБЕЩАНИЯ\n'+'\n'.join(promises))
        self.clear(self.history)
        for e in reversed(s['events'][-180:]):self.history.insert('','end',iid=str(e['id']),values=(e['id'],e['week'],e['kind'],e['text']))
        self.clear(self.actors)
        roles={'leader':'Лидер','journalist':'Редактор','employer':'Работодатель','activist':'Активист','official':'Администратор','organizer':'Организатор'}
        for aid,a in s['actors'].items():self.actors.insert('','end',iid=aid,values=(a['name'],roles.get(a['role'],a['role']),a['goal'],a['age'],'действует' if a['alive'] else 'выбыл'))
        lines=['ВЫБОРЫ — независимый цикл. Без игрока тоже проходят.','']
        for e in reversed(s['elections'][-8:]):
            lines+=['Неделя '+str(e['week'])+' · '+e['system']+' · явка '+str(round(e['turnout'],1))+'% · '+str(e['voters'])+' голосов']
            for pid,votes in e['votes'].items():lines.append(s['parties'][pid]['name']+': '+str(votes)+' голосов · '+str(round(e['shares'][pid],1))+'% · '+str(e['seats'][pid])+' мест')
            lines+=['Правительство: '+', '.join(s['parties'][p]['name'] for p in e['government']),'']
        if not s['elections']:lines.append('Первые выборы ещё не состоялись. Нажмите «До выборов».')
        self._set(self.elections,'\n'.join(lines));self.draw_city();self.refresh_civic()
        for key,callback,detail in [('homes',self.household_details,self.home_text),('actors',self.actor_details,self.actor_text),('people',self.cohort_details,self.details),('history',self.event_details,self.event_text)]:
            tree=getattr(self,key);old=selected[key]
            if old and tree.exists(old[0]):tree.selection_set(old[0]);callback()
            else:self._set(detail,'Выберите строку, чтобы увидеть текущие подробности.')

    def refresh_people(self):
        self.clear(self.people);tag=next((k for k,v in self.world.data['tags'].items() if v==self.filter.get()),'all')
        s=self.world.state
        tag2=next((k for k,v in self.world.data['tags'].items() if v==self.filter2.get()),'all')
        selected=affected(s,tag+'&'+tag2)
        self.filter_count.configure(text='В выборке: '+str(sum(c['population'] for c in selected)))
        short={'student':'студ.','elder':'пенс.','business':'бизнес','worker':'раб.','parent':'родит.','single':'одиноч.','secular':'светск.','religious':'религ.','lower':'низш.','middle':'средн.','upper':'высш.'}
        for c in selected:
            active=[p for p,x in s['parties'].items() if x['active']];best=max(active,key=lambda p:attraction(s,c,p)[0])
            tags=' · '.join(short[t] for t in c['tags'])
            self.people.insert('','end',iid=c['id'],values=(c['id'],s['districts'][c['district']]['name'],tags,c['population'],round(c['ideology']['economy']),round(c['ideology']['tradition']),s['parties'][best]['name']))

    def cohort_details(self,event=None):
        selected=self.people.selection()
        if not selected:return
        c=next(x for x in self.world.state['cohorts'] if x['id']==selected[0]);lines=[', '.join(self.world.data['tags'][t] for t in c['tags']), 'Один человек входит в несколько признаков, но учитывается в населении один раз.','Среднее + разброс; это не подробная биография каждого гражданина.']
        part_names={'ideology':'идеология','trust':'доверие','memory':'память','leader':'лидер','familiarity':'узнаваемость','identity':'идентичность','editor':'прямой бонус','civic':'общественные связи'}
        for pid,p in self.world.state['parties'].items():
            if p['active']:
                score,parts=attraction(self.world.state,c,pid);lines.append(p['name']+' · '+str(round(score,1))+'/100 · '+', '.join(part_names[k]+'='+str(round(v,1)) for k,v in parts.items()))
        self._set(self.details,'\n'.join(lines))

    def event_details(self,event=None):
        ids=self.history.selection()
        if not ids:return
        e=next(e for e in self.world.state['events'] if str(e['id'])==ids[0]);causes=[]
        for eid in e['causes']:
            parent=next((p for p in self.world.state['events'] if p['id']==eid),None);causes.append(parent['text'] if parent else 'Причина #'+str(eid)+' вышла за предел сохранённой хроники')
        reached=sum(c['population']*e['reach'].get(c['id'],0) for c in self.world.state['cohorts'])
        causes=['  '*row['depth']+'#'+str(row['id'])+' '+row['text'] for row in civic.ancestry(self.world.state,e['id'])]
        self._set(self.event_text,e['text']+'\nФакт: '+str(e['truth'])+'; приблизительный охват: '+str(round(reached))+' жителей\nПричины: '+('; '.join(causes) or 'самостоятельные решения / текущие условия')+'\nИзбиратели знают это не одновременно. ID можно использовать: Раскрыть событие '+str(e['id']))

    def actor_details(self,event=None):
        ids=self.actors.selection()
        if not ids:return
        a=self.world.state['actors'][ids[0]];dec=a['decision']
        relations=[self.world.state['actors'][k]['name']+': '+str(v) for k,v in a['relations'].items() if k in self.world.state['actors']]
        lines=[ids[0]+' · '+a['name']+' · '+a['goal'],'Честность '+str(a['honesty'])+' · компетентность '+str(a['competence'])+' · влияние '+str(a['influence']),
               'Решение на неделе '+str(dec['week'])+': '+agents.NAMES[dec['action']]+' · '+dec['reason']]
        for r in dec['options']:lines.append(agents.NAMES[r['action']]+': оценка '+str(round(r['score'],1))+' · '+r['reason'])
        pid=next((p for p,x in self.world.state['parties'].items() if x['leader']==ids[0]),None)
        if pid:
            i=self.world.state['parties'][pid]['intel'];lines.append('Знания политика: выборка '+str(i['sample'])+' наблюдений, неделя '+str(i['week'])+'; оценки с шумом, не точные предпочтения всех жителей.')
        else:lines.append('У этой роли ещё нет общего планировщика: её автономные правила остаются частичными.')
        lines.append('Отношения (частичная модель): '+', '.join(relations));self._set(self.actor_text,'\n'.join(lines))

    def refresh_civic(self):
        s=self.world.state;z=s['civic'];previous={k:t.selection() for k,t in self.civic_views.items()}
        for t in self.civic_views.values():self.clear(t)
        for iid,i in z['institutions'].items():self.civic_views['institutions'].insert('','end',iid=iid,values=(iid,civic.KINDS[i['kind']]+' / '+s['districts'][i['district']]['name'],round(i['capacity']),round(i['staff']),round(i['served']),round(i['queue']),round(i['delay'],1)))
        for p in reversed(s['projects']):self.civic_views['projects'].insert('','end',iid=p['id'],values=(p['id'],s['parties'][p['party']]['name'],civic.STAGES[p['stage']],round(p['progress']),round(p['spent']),'да' if p['public_open'] else 'нет'))
        for g in z['associations']:self.civic_views['associations'].insert('','end',iid=g['id'],values=(g['id'],s['districts'][g['district']]['name'],sum(g['members'].values()),round(g['resources']),round(g['fatigue']),'действует' if g['active'] else 'архив'))
        kinds={'proposal':'предложение','status':'отчёт','inspection':'акт проверки','opening_claim':'объявление открытия'}
        for d in reversed(z['documents']):self.civic_views['documents'].insert('','end',iid=d['id'],values=(d['id'],d['project'],kinds.get(d['kind'],d['kind']),civic.STAGES[d['stage']],round(d['access'],2),'да' if d['published'] else 'нет'))
        for key,t in self.civic_views.items():
            if previous[key] and t.exists(previous[key][0]):t.selection_set(previous[key][0]);self.civic_details_show(key)
            else:self._set(self.civic_details[key],'Выберите строку. Это данные мира: участники знают не всё, что видит бог.')
        lines=['Изменение средней привлекательности партий, не проценты голосов.','Компоненты — измеренный сдвиг. Связанные события — контекст, не доказанный вклад каждого события.','']
        for row in reversed(z['changes'][-8:]):
            lines.append('Неделя '+str(row['week'])+' · '+s['parties'][row['party']]['name']+' · '+str(round(row['delta'],3))+' пункта')
            lines.append(', '.join({'ideology':'идеология','trust':'доверие','memory':'память','leader':'лидер','familiarity':'узнаваемость','identity':'идентичность','editor':'прямой бонус','civic':'объединения'}.get(k,k)+' '+str(round(v,3)) for k,v in row['parts'].items() if abs(v)>.001))
            for eid in row['causes'][:3]:
                lines.extend('  '*r['depth']+'#'+str(r['id'])+' '+r['text'] for r in civic.ancestry(s,eid,5))
            lines.append('')
        self._set(self.cause_text,'\n'.join(lines))

    def civic_details_show(self,key):
        tree=self.civic_views[key];ids=tree.selection()
        if not ids:return
        s=self.world.state;z=s['civic'];iid=ids[0];lines=[]
        if key=='institutions':
            i=z[key][iid];lines=[iid+' · '+civic.KINDS[i['kind']], 'Спрос '+str(round(i['demand']))+' · реально обслужено '+str(round(i['served']))+' · не обслужено '+str(round(i['queue'])), 'Вместимость '+str(round(i['capacity']))+' · персонал '+str(round(i['staff']))+'% · состояние '+str(round(i['condition']))+'%', 'Новое здание без персонала не устраняет очередь. Задержка — модельный индекс, не реальные часы.']
            if i['cause']:lines.extend('#'+str(r['id'])+' '+r['text'] for r in civic.ancestry(s,i['cause'],8))
        elif key=='projects':
            p=next(p for p in s[key] if p['id']==iid);lines=[iid+' · '+civic.STAGES[p['stage']], 'Стоимость '+str(round(p['cost'],1))+' · списано '+str(round(p['spent'],1))+' · готовность '+str(round(p['progress'],1))+'%', 'Политическое объявление открытия: '+('есть' if p['public_open'] else 'нет')+'; реально работает: '+('да' if p['stage']=='operating' else 'нет'), 'Учреждение: '+(p['institution'] or 'перенесённый проект прежней версии')]
            lines.extend('  '*r['depth']+'#'+str(r['id'])+' '+r['text'] for r in civic.ancestry(s,p['last_event'],12) if p['last_event'])
        elif key=='associations':
            g=next(g for g in z[key] if g['id']==iid);lines=[iid+' · требование: задержка не выше '+str(round(g['demand'],1)), 'Представитель: '+g['leader']+'; участники — подмножество жителей, не добавочное население.', 'Членство в нескольких объединениях возможно; поддержка требования не означает поддержку партии.']
            for pid,pos in g['positions'].items():lines.append(s['parties'][pid]['name']+': '+civic.REACTIONS[pos['reaction']]+' · отношение участников '+str(round(g['stances'].get(pid,0),1)))
            lines.append('Когорты-участники: '+', '.join(cid+': '+str(n) for cid,n in g['members'].items()))
        else:
            d=next(d for d in z[key] if d['id']==iid);lines=[iid+' · проект '+d['project']+' · неделя '+str(d['week']), 'Снимок факта на дату: '+civic.STAGES[d['stage']]+' · готовность '+str(round(d['progress'],1))+'% · расход '+str(round(d['spent'],1)), 'Объявлено открытие: '+('да' if d['public_open'] else 'нет')+' · опубликовано: '+('да' if d['published'] else 'нет')+' · проверено: '+('да' if d['checked'] else 'нет'), 'Доступ можно облегчить силой: Облегчить обнаружение документа '+iid+'. Это не заставит журналиста публиковать.']
            for case in z['cases']:
                if iid in case['documents']:lines.append('Расследование '+case['id']+' · '+{'checking':'проверяется','published':'опубликовано','closed':'закрыто'}[case['stage']]+' · '+case['result'])
        self._set(self.civic_details[key],'\n'.join(lines))

    def household_details(self,event=None):
        ids=self.homes.selection()
        if not ids:return
        c=next(c for c in self.world.state['cohorts'] if c['id']==ids[0]);h=c['household'];life=c['life'];d=self.world.state['districts'][c['district']]
        lines=[c['id']+' · '+', '.join(self.world.data['tags'][t] for t in c['tags']),
               'Население '+str(c['population'])+' · среднее представительное домохозяйство, не '+str(c['population'])+' отдельных семей.',
               'Защищённость '+str(round(h['security'],1))+'/100 · нехватка средств '+str(round(h['shortage']))+' · свободное время '+str(round(h['free_time'],1))+' · усталость '+str(round(h['fatigue'],1)),
               'Решение: '+living.ACTIONS[life['action']]+' · курс '+str(h['training'])+'/8 недель · квалификация '+str(h['skill'])+' · завершено курсов '+str(life['completed'])]
        lines.append('План расходов при текущем решении (не проводки прошлой недели):')
        for key,value in living.expenses(c,d,self.world.data['living']).items():lines.append({'food':'Еда','housing':'Жильё','transport':'Транспорт','health':'Здоровье','dependents':'Иждивенцы','study':'Обучение'}[key]+': '+str(round(value)))
        if h['ledger']:
            l=h['ledger'];lines+=['Денежный журнал последней недели:','Доход '+str(round(l['income']))+' − оплачено '+str(round(l['paid']))+' − проценты '+str(round(l['interest']))+' = изменение чистого резерва '+str(round(h['balance'])),
                'Из резерва '+str(round(l['withdrawal']))+' · новый кредит '+str(round(l['loan']))+' · погашено '+str(round(l['repayment']))+' · отложено '+str(round(l['deposit']))]
        else:lines.append('Недельных проводок ещё нет: перемотайте одну неделю.')
        lines+=['Почему выбрано:']+[living.ACTIONS[r['action']]+': '+str(round(r['score'],1))+' · '+r['reason'] for r in life['options']]
        self._set(self.home_text,'\n'.join(lines))

    def explain(self):
        dlg=tk.Toplevel(self);dlg.title('Структура вмешательства');dlg.geometry('700x450')
        text=self._text(dlg,20);self._set(text,json.dumps(self.pending.record() if self.pending else {'note':'Сначала подготовьте вмешательство'},ensure_ascii=False,indent=2))

    def _clipboard_key(self,e):
        if e.keysym.lower() in ('v','м','cyrillic_em') or (self.tk.call('tk','windowingsystem')=='win32' and e.keycode==86):return self.paste(e)

    def paste(self,event=None):
        try:
            value=normalize_clipboard(self.clipboard_get())
            try:a,b=self.entry.index('sel.first'),self.entry.index('sel.last')
            except tk.TclError:a=b=self.entry.index('insert')
            old=self.entry.get()
            if len(old[:a]+value+old[b:])>2000:raise RuleError('После вставки больше 2000 символов')
            self.entry.delete(a,b);self.entry.insert(a,value);self.entry.icursor(a+len(value));self.entry.focus_set();self.cancel()
        except (tk.TclError,RuleError) as exc:messagebox.showwarning('Буфер',str(exc) if isinstance(exc,RuleError) else 'В буфере нет текста',parent=self)
        return 'break'

    def context(self,e):
        menu=tk.Menu(self,tearoff=False);menu.add_command(label='Вставить',command=self.paste);menu.add_command(label='Копировать',command=lambda:self.entry.event_generate('<<Copy>>'))
        try:menu.tk_popup(e.x_root,e.y_root)
        finally:menu.grab_release()

    def _shortcut_scroll(self):
        self.custom_canvas.configure(scrollregion=self.custom_canvas.bbox('all'))
        if self.custom_inner.winfo_reqwidth()>self.custom_canvas.winfo_width():self.custom_scroll.pack(fill='x')
        else:self.custom_scroll.pack_forget()

    def refresh_shortcuts(self):
        self.shortcut_box.configure(values=[x['name'] for x in self.shortcuts.items]);self.shortcut_var.set(self.shortcuts.items[0]['name'] if self.shortcuts.items else '')
        for w in self.custom_inner.winfo_children():w.destroy()
        for item in self.shortcuts.items:
            self._button(self.custom_inner,item['name'],lambda name=item['name']:self._use_shortcut(name))
        if self.shortcuts.items:self.custom_bar.pack(fill='x',pady=2,after=self.shortcut_box.master)
        else:self.custom_bar.pack_forget()

    def _use_shortcut(self,name):
        self.shortcut_var.set(name);self.prepare_shortcut()

    def prepare_shortcut(self):
        item=next((x for x in self.shortcuts.items if x['name']==self.shortcut_var.get()),None)
        if not item:return
        self.entry.delete(0,'end');self.entry.insert(0,item['text']);self.prepare()

    def add_shortcut(self,item=None):
        dlg=tk.Toplevel(self);dlg.title('Моя божественная сила');dlg.geometry('600x330')
        ttk.Label(dlg,text='Название кнопки / шаблона:').pack(anchor='w',padx=12,pady=6);name=ttk.Entry(dlg);name.pack(fill='x',padx=12)
        if item:name.insert(0,item['name'])
        text=tk.Text(dlg,height=6,wrap='word');text.pack(fill='both',expand=True,padx=12,pady=6);text.insert('1.0',item['text'] if item else self.entry.get())
        ttk.Label(dlg,text='Шаблон проходит тот же разбор. Неизвестные механики не исполняются.',wraplength=560).pack(padx=12)
        buttons=ttk.Frame(dlg);buttons.pack(fill='x',padx=12,pady=8)
        def save():
            try:self.shortcuts.put(name.get(),normalize_clipboard(text.get('1.0','end-1c')),item['id'] if item else None)
            except (DataError,RuleError) as exc:messagebox.showerror('Моя сила',str(exc),parent=dlg);return
            self.refresh_shortcuts();dlg.destroy()
        self._button(buttons,'Сохранить',save)
        if item:
            def remove():
                if not messagebox.askyesno('Удалить','Удалить этот шаблон?',parent=dlg):return
                try:self.shortcuts.delete(item['id'])
                except DataError as exc:messagebox.showerror('Моя сила',str(exc),parent=dlg);return
                self.refresh_shortcuts();dlg.destroy()
            self._button(buttons,'Удалить',remove)
        self._button(buttons,'Отмена',dlg.destroy,side='right');dlg.grab_set()

    def edit_shortcut(self):
        item=next((x for x in self.shortcuts.items if x['name']==self.shortcut_var.get()),None)
        if item:self.add_shortcut(item)

    def power_menu(self):
        self.running=False;self.run_btn.configure(text='▶ Наблюдать');dlg=tk.Toplevel(self);dlg.title('Конструктор косвенного вмешательства');dlg.geometry('650x520')
        fields={};powers=list(self.world.data['powers']);targets=['all']+list(self.world.state['districts'])+list(self.world.data['tags']);topics=['']+list(self.world.data['topics'])
        options=[('power','Механизм',powers,[self.world.data['powers'][p]['name'] for p in powers]),('target','Аудитория',targets,['Весь город']+[self.world.state['districts'].get(t,{}).get('name',self.world.data['tags'].get(t,t)) for t in targets[1:]]),('topic','Тема',topics,['Без темы']+[self.world.data['topics'][t]['name'] for t in topics[1:]])]
        for key,label,ids,names in options:
            row=ttk.Frame(dlg);row.pack(fill='x',padx=12,pady=6);ttk.Label(row,text=label,width=12).pack(side='left');box=ttk.Combobox(row,state='readonly',values=names,width=38);box.current(0);box.pack(side='left');fields[key]=(box,ids)
        values={}
        for key,label,default in [('strength','Сила −30..30',15),('duration','Срок 1..12',4),('event_id','ID факта',1)]:
            row=ttk.Frame(dlg);row.pack(fill='x',padx=12,pady=4);ttk.Label(row,text=label,width=16).pack(side='left');var=tk.StringVar(value=str(default));ttk.Entry(row,textvariable=var,width=10).pack(side='left');values[key]=var
        aid_list=[a for a,x in self.world.state['actors'].items() if x['alive']]
        for key,label in [('actor_a','Первый персонаж'),('actor_b','Второй персонаж')]:
            row=ttk.Frame(dlg);row.pack(fill='x',padx=12,pady=4);ttk.Label(row,text=label,width=20).pack(side='left');box=ttk.Combobox(row,state='readonly',values=[a+' · '+self.world.state['actors'][a]['name'] for a in aid_list],width=38);box.current(0 if key=='actor_a' else min(1,len(aid_list)-1));box.pack(side='left');fields[key]=(box,aid_list)
        for key,label in [('document_id','Документ D…'),('association_id','Объединение G…')]:
            row=ttk.Frame(dlg);row.pack(fill='x',padx=12,pady=4);ttk.Label(row,text=label,width=20).pack(side='left');var=tk.StringVar();ttk.Entry(row,textvariable=var,width=16).pack(side='left');values[key]=var
        ttk.Label(dlg,text='Сила меняет среду, не популярность. Положительная погода = опасность; отрицательная = смягчение.',wraplength=520).pack(padx=12,pady=4)
        def apply():
            try:
                cmd={k:ids[box.current()] for k,(box,ids) in fields.items()};cmd.update({'strength':float(values['strength'].get()),'duration':int(values['duration'].get())})
                if cmd['power']=='reveal':cmd['event_id']=int(values['event_id'].get())
                if cmd['power']!='encounter':cmd.pop('actor_a');cmd.pop('actor_b')
                if cmd['power']=='discovery':cmd['document_id']=values['document_id'].get().strip().upper()
                if cmd['power']=='coordination' and values['association_id'].get().strip():cmd['association_id']=values['association_id'].get().strip().upper()
                scratch=copy.deepcopy(self.world.state)
                from .world import apply_power
                _,cost=apply_power(scratch,self.world.data,cmd)
                if not messagebox.askyesno('Вмешательство','Цена '+str(cost)+' влияния. Изменить обстоятельства?',parent=dlg):return
                self.dispatch('power',cmd)
            except (ValueError,RuleError,DataError) as exc:messagebox.showerror('Сила',str(exc),parent=dlg);return
            self.cancel();self.refresh();dlg.destroy()
        b=ttk.Frame(dlg);b.pack(pady=8);self._button(b,'Проверить и применить',apply);self._button(b,'Отмена',dlg.destroy);dlg.grab_set()

    def direct_menu(self):
        self.running=False;self.run_btn.configure(text='▶ Наблюдать');dlg=tk.Toplevel(self);dlg.title('ПРЯМОЕ УПРАВЛЕНИЕ — редактор мира');dlg.geometry('650x420')
        ttk.Label(dlg,text='Здесь результат задаётся напрямую. Запись попадёт в журнал редактора.\nОткат возвращает весь мир к снимку до операции (включая прошедшее время).',wraplength=620,foreground='#9B3B35').pack(padx=12,pady=10)
        ops=[('popularity','Добавить пункты привлекательности'),('dissolve','Распустить партию'),('create','Создать партию'),('ideology','Изменить идеологию партии'),('rules','Изменить правила выборов'),('resource','Изменить район'),('retire','Вывести персонажа')]
        pids=[p for p,x in self.world.state['parties'].items() if x['active']];dids=list(self.world.state['districts']);aids=[a for a,x in self.world.state['actors'].items() if x['alive']]
        fields={}
        configs=[('op','Операция',[k for k,_ in ops],[v for _,v in ops]),('party','Партия',pids,[self.world.state['parties'][p]['name'] for p in pids]),('target','Аудитория',['all']+dids,['Весь город']+[self.world.state['districts'][d]['name'] for d in dids]),('axis','Идеологическая ось',list(self.world.data['axes']),list(self.world.data['axes'].values())),('key','Правило',['threshold','election_period','election_system'],['Порог, %','Период, недель','Система (код)']),('field','Показатель',['income','infra','jobs','access','health','solidarity'],['Доход','Инфраструктура','Занятость','Доступ','Здоровье','Солидарность']),('actor','Персонаж',aids,[self.world.state['actors'][a]['name'] for a in aids])]
        for key,label,ids,names in configs:
            row=ttk.Frame(dlg);row.pack(fill='x',padx=12,pady=3);ttk.Label(row,text=label,width=22).pack(side='left');box=ttk.Combobox(row,state='readonly',values=names,width=40);box.current(0);box.pack(side='left');fields[key]=(box,ids)
        row=ttk.Frame(dlg);row.pack(fill='x',padx=12,pady=4);ttk.Label(row,text='Значение / имя новой партии',width=27).pack(side='left');value=ttk.Entry(row,width=35);value.insert(0,'20');value.pack(side='left')
        ttk.Label(dlg,text='Системы: proportional, majoritarian, mixed. Новая партия начинает с нейтральной идеологии.',wraplength=620).pack(padx=12,pady=5)
        def apply():
            selected={k:ids[box.current()] for k,(box,ids) in fields.items()};op=selected['op'];raw=value.get().strip()
            try:
                command={'op':op}
                if op in ('popularity','dissolve','ideology'):command['party']=selected['party']
                if op=='popularity':command.update(target=selected['target'],value=float(raw))
                elif op=='create':command.update(name=raw,ideology={a:0 for a in self.world.data['axes']})
                elif op=='ideology':command.update(axis=selected['axis'],value=float(raw))
                elif op=='rules':command.update(key=selected['key'],value=raw if selected['key']=='election_system' else int(raw) if selected['key']=='election_period' else float(raw))
                elif op=='resource':command.update(district=selected['target'],field=selected['field'],value=float(raw))
                elif op=='retire':command['actor']=selected['actor']
                if not messagebox.askyesno('Прямой редактор','Применить прямое изменение? Оно будет явно отмечено.',parent=dlg):return
                self.dispatch('direct',command)
            except (ValueError,RuleError,DataError) as exc:messagebox.showerror('Редактор',str(exc),parent=dlg);return
            self.cancel();self.refresh();dlg.destroy()
        b=ttk.Frame(dlg);b.pack(pady=8);self._button(b,'Применить напрямую',apply);self._button(b,'Отмена',dlg.destroy);dlg.grab_set()

    def undo(self):
        self.running=False
        if self.link:
            messagebox.showinfo('Откат','Откат общего мира отключён при соединении. Сохраните мир, отключите связь и откатите у создателя.',parent=self);return
        if not messagebox.askyesno('Откат','Вернуть весь мир к снимку до последней прямой операции? Последующие недели и чудеса тоже будут отменены.',parent=self):return
        try:self.world.undo()
        except RuleError as exc:messagebox.showwarning('Откат',str(exc),parent=self);return
        self.cancel();self.refresh()

    def refresh_territories(self):
        s=self.world.state;t=s['territory'];self.clear(self.world_tree)
        for cid,city in sorted(territories.cities(s).items()):
            name=t['meta'][cid]['name']+' / '+t['regions'][t['meta'][cid]['region']]['name'] if t else 'Кочто / городской мир'
            self.world_tree.insert('','end',iid=cid,values=(name,sum(c['population'] for c in city['cohorts']),round(sum(d['jobs'] for d in city['districts'].values())/4),round(sum(d['income'] for d in city['districts'].values())/4),sum(c['stage']!='resolved' for c in city['crises']['items'])))
        lines=['Каждый город рассчитывается каждую неделю, независимо от открытой вкладки. Локальные ID относятся к выбранному городу; голосование разных уровней учитывает одних жителей по одному разу на каждом уровне.']
        if t:
            lines.append('Общий ресурс влияния сохраняется при переключении. Регион — 2 города; федерация — 2 региона / 4 города: ограниченный мир, не модель всей страны.')
            for rid,r in sorted(t['regions'].items()):
                lines.append(r['name']+' · бюджет '+str(round(r['budget']))+' · власть '+(', '.join(self.world.data['parties'][p]['name'] for p in r['government']) or 'до первых выборов'))
            if t['scale']=='federation':lines.append('Федерация · бюджет '+str(round(t['federal']['budget']))+' · власть '+(', '.join(self.world.data['parties'][p]['name'] for p in t['federal']['government']) or 'до первых выборов'))
            lines+=['Региональные и федеральные отделения имеют собственных руководителей, средства, опросы и кампании. Избиратели знают программы отдельно на каждом уровне; их голоса не копируются с городского результата.','Регион распределяет помощь городам, федерация — регионам; приоритет зависит от программы правящей партии. Регулярный доход казны внешний; это не замкнутая налоговая модель.']
            lines.extend('Неделя '+str(e['week'])+' · '+e['text'] for e in t['events'][-8:])
        else:lines.append('Для региона или федерации: Новый мир → свободный мир → выбрать масштаб. Сценарий комбината рассчитан на город.')
        self._set(self.world_text,'\n\n'.join(lines));selected=self.crisis_tree.selection();self.clear(self.crisis_tree)
        for c in s['crises']['items']:self.crisis_tree.insert('','end',iid=c['id'],values=(c['id'],crises.KINDS[c['kind']],crises.STAGES[c['stage']],round(c['material']),round(c['capacity']),round(c['division'])))
        self._set(self.crisis_text,'Обязательство: '+crises.GOALS.get(s['crises']['goal'],'не принято')+'. Выберите кризис. Тяжесть, способность решения и раскол — разные модельные показатели. Мирный протест не считается поражением.')

        if selected and self.crisis_tree.exists(selected[0]):self.crisis_tree.selection_set(selected[0]);self.crisis_details()

    def upper_menu(self):
        if not self.world.state['territory']:messagebox.showinfo('Верхние партии','Доступно в регионе или федерации.',parent=self);return
        dlg=tk.Toplevel(self);dlg.title('Отделения верхних уровней — независимая политика');dlg.geometry('1000x650')
        self.upper_dialog=dlg
        t=self.world.state['territory'];lids=list(upper_politics.levels(t));labels=[t['regions'][lid]['name'] if lid!='federal' else 'Федерация' for lid in lids]
        tools=ttk.Frame(dlg);tools.pack(fill='x',padx=8,pady=8)
        scope=ttk.Combobox(tools,state='readonly',values=labels,width=30);scope.pack(side='left');scope.current(0)
        turnout=ttk.Label(tools);turnout.pack(side='left',padx=16)
        tree=self._tree(dlg,[('party','Партия'),('leader','Руководитель'),('share','Прогноз %'),('funds','Средства'),('org','Организация')],5);tree.column('leader',width=220,minwidth=180)
        text=self._text(dlg,12)
        self.upper_tree=tree;self.upper_text=text;self.upper_scope=scope
        def details(event=None):
            if not self.world.state['territory'] or set(upper_politics.levels(self.world.state['territory']))!=set(lids):return
            selected=tree.selection()
            if not selected:return
            lid=lids[scope.current()];pid=selected[0];b=self.world.state['territory']['politics'][lid]['branches'][pid];a=b['leader'];intel=b['intel']
            lines=[a['name']+' · ID '+a['id']+' · возраст '+str(a['age'])+' · компетентность '+str(a['competence'])+' · влияние '+str(a['influence']),
             'Программа: '+', '.join(self.world.data['axes'][axis]['name']+' '+str(round(v,1)) if isinstance(self.world.data['axes'][axis],dict) else str(self.world.data['axes'][axis])+' '+str(round(v,1)) for axis,v in b['ideology'].items()),
             'Последнее решение: '+upper_politics.ACTIONS.get(b['decision']['action'],'сохранить средства')+' · '+b['decision']['reason'],
             'Знания: '+str(len(intel['sample']))+' шумных наблюдений, неделя '+str(intel['week'])+'. Отделение не читает точные предпочтения всех жителей.',
             'Когорты хранят отдельное знание этой программы. Передача казны сама по себе не назначает победителя; её видимость и опыт услуги разделены.']
            lines.extend('Неделя '+str(f['week'])+' · '+f['text'] for f in self.world.state['territory']['politics'][lid]['facts'][-6:] if f['party']==pid)
            self._set(text,'\n\n'.join(lines))
        def render(event=None):
            if not dlg.winfo_exists():return
            if not self.world.state['territory'] or set(upper_politics.levels(self.world.state['territory']))!=set(lids):dlg.destroy();return
            lid=lids[scope.current()];t=self.world.state['territory'];shares,participation=upper_politics.forecast(t,lid,territories.cities(self.world.state));turnout.configure(text='Оценочная явка '+str(round(participation,1))+'%')
            selected=tree.selection();self.clear(tree)
            for pid,b in t['politics'][lid]['branches'].items():tree.insert('','end',iid=pid,values=(self.world.data['parties'][pid]['name'],b['leader']['name'],round(shares[pid],1),round(b['funds'],1),round(b['organization'],1)))
            tree.selection_set(selected[0] if selected and tree.exists(selected[0]) else tree.get_children()[0]);details()
        scope.bind('<<ComboboxSelected>>',render);tree.bind('<<TreeviewSelect>>',details);self._upper_refresh=render;render()
        self._button(tools,'Обновить',render)
        ttk.Label(dlg,text='Три общих партийных идентичности, отдельные отделения. Это не полные биографии и не вся страна.',wraplength=920).pack(fill='x',padx=8,pady=8)

    def select_city(self):
        selected=self.world_tree.selection()
        if not selected:return
        try:self.dispatch('territory',{'op':'select','value':selected[0]})
        except (RuleError,DataError) as exc:messagebox.showwarning('Территория',str(exc),parent=self);return
        self.cancel();self.refresh();self.tabs.select(self.frames['city'])

    def choose_crisis_goal(self):
        try:self.dispatch('territory',{'op':'goal','value':list(crises.GOALS)[self.crisis_goal.current()]})
        except (RuleError,DataError) as exc:messagebox.showwarning('Кризис',str(exc),parent=self);return
        self.cancel();self.refresh()

    def crisis_details(self,event=None):
        ids=self.crisis_tree.selection()
        if not ids:return
        c=next(c for c in self.world.state['crises']['items'] if c['id']==ids[0]);lines=[c['id']+' · '+crises.KINDS[c['kind']]+' · '+crises.STAGES[c['stage']], 'Причина: '+{'jobs':'недостаток занятости','services':'нагрузка учреждений и задержки обслуживания','trust':'низкое доверие к действующей власти'}[c['kind']], 'Возраст '+str(self.world.state['week']-c['born'])+' недель; участники собрания: '+str(c['members']), 'Восстановление: '+str(c['low_weeks'])+'/4 последовательных недель низкого давления. Реальные проекты могут помочь, но финал не назначается.']+c['epilogue']
        lines=lines[:3]+['Граница потерь: '+crisis_life.METRICS[self.world.state['crises']['boundary']['metric']]+' ≥ '+str(self.world.state['crises']['boundary']['floor'])]+crisis_life.describe(self.world.state,c)
        lines.extend('#'+str(r['id'])+' '+r['text'] for r in civic.ancestry(self.world.state,c['last_event'],8));self._set(self.crisis_text,'\n\n'.join(lines))

    def crisis_boundary(self):
        dlg=tk.Toplevel(self);dlg.title('Что особенно важно сохранить?');dlg.geometry('530x230')
        ttk.Label(dlg,text='Это граница оценки итога, не приказ людям. Пересмотр не стирает прежний выбор.',wraplength=480).pack(padx=16,pady=12)
        labels={'security':'Средняя защищённость семей','health':'Среднее здоровье','solidarity':'Соседские связи'}
        metric=ttk.Combobox(dlg,state='readonly',values=list(labels.values()),width=45);metric.pack(pady=4);metric.current(list(labels).index(self.world.state['crises']['boundary']['metric']))
        value=ttk.Entry(dlg);value.pack(pady=4);value.insert(0,str(self.world.state['crises']['boundary']['floor']))
        def accept():
            try:self.dispatch('territory',{'op':'boundary','value':{'metric':list(labels)[metric.current()],'floor':float(value.get())}})
            except (ValueError,RuleError,DataError) as exc:messagebox.showwarning('Граница',str(exc),parent=dlg);return
            self.cancel();self.refresh();dlg.destroy()
        buttons=ttk.Frame(dlg);buttons.pack(fill='x',padx=16,pady=12)
        self._button(buttons,'Сохранить границу',accept);self._button(buttons,'Отмена',dlg.destroy)

    def change_goal(self):
        try:self.dispatch('story',{'op':'goal','value':list(story.GOALS)[self.goal_box.current()]})
        except (RuleError,DataError) as exc:messagebox.showwarning('Обязательство',str(exc),parent=self);return
        self.cancel();self.refresh()

    def continue_story(self):
        try:self.dispatch('story',{'op':'continue','value':None})
        except (RuleError,DataError) as exc:messagebox.showwarning('История',str(exc),parent=self);return
        self.cancel();self.refresh()

    def new_world(self):
        if self.link:messagebox.showinfo('Новый мир','Сначала отключите P2P.',parent=self);return
        self.running=False
        dlg=tk.Toplevel(self);dlg.title('Новый мир — зачем вмешиваться?');dlg.geometry('670x490')
        ttk.Label(dlg,text='Последняя зима комбината',font=('Arial',16,'bold')).pack(anchor='w',padx=16,pady=12)
        ttk.Label(dlg,text='Предприятие даёт работу и загрязняет район. Помогите людям пережить перемены. Выборы изменят возможности, но их победитель не задан. История завершается после 26 недель; мир можно продолжить.',wraplength=620,justify='left').pack(anchor='w',padx=16,pady=8)
        mode=tk.StringVar(value='last_winter')
        ttk.Radiobutton(dlg,text='Сценарий с обязательством и эпилогом',variable=mode,value='last_winter').pack(anchor='w',padx=16,pady=4)
        ttk.Radiobutton(dlg,text='Свободный мир — без обязательного финала',variable=mode,value='free').pack(anchor='w',padx=16,pady=4)
        ttk.Label(dlg,text='Масштаб мира (сценарий выше поддерживает только город):').pack(anchor='w',padx=16,pady=4)
        scale=ttk.Combobox(dlg,state='readonly',values=list(territories.SCALES.values()),width=60);scale.pack(padx=16,pady=4);scale.current(0)
        goal=ttk.Combobox(dlg,state='readonly',values=list(story.GOALS.values()),width=60);goal.pack(padx=16,pady=10);goal.current(0)
        ttk.Label(dlg,text='Зерно города (число или пусто):').pack(anchor='w',padx=16);seed=ttk.Entry(dlg);seed.pack(fill='x',padx=16,pady=6)
        def launch():
            try:w=World(int(seed.get()) if seed.get().strip() else None,scenario=None if mode.get()=='free' else 'last_winter',goal=list(story.GOALS)[goal.current()],scale=list(territories.SCALES)[scale.current()])
            except (ValueError,RuleError,DataError) as exc:messagebox.showerror('Новый мир',str(exc),parent=dlg);return
            if not messagebox.askyesno('Новый мир','Несохранённые изменения будут потеряны. Начать?',parent=dlg):return
            self.world=w;self.cancel();self.refresh();self.tabs.select(self.frames['story'] if w.state['story'] else self.frames['world']);dlg.destroy()
        buttons=ttk.Frame(dlg);buttons.pack(fill='x',padx=16,pady=10);self._button(buttons,'Начать',launch);self._button(buttons,'Отмена',dlg.destroy)

    def save(self):
        self.running=False;path=filedialog.asksaveasfilename(initialdir=save_dir(),initialfile='god_world.json',defaultextension='.json',filetypes=[('Мир бога','*.json')])
        if path:
            try:self.world.save(path)
            except DataError as exc:messagebox.showerror('Сохранение',str(exc),parent=self)

    def load(self):
        if self.link:
            messagebox.showinfo('Загрузка','Сначала отключите P2P. Создатель загружает мир и открывает новую связь.',parent=self);return
        self.running=False;path=filedialog.askopenfilename(initialdir=save_dir(),filetypes=[('Мир бога','*.json')])
        if path:
            try:self.world.load(path)
            except DataError as exc:messagebox.showerror('Загрузка',str(exc)+'\nСтарые сейвы кандидата — в отдельном режиме.',parent=self);return
            self.cancel();self.refresh()
            if self.world.migration_notice:messagebox.showinfo('Перенос сохранения',self.world.migration_notice,parent=self)

    def export_history(self):
        path=filedialog.asksaveasfilename(initialfile='god_history.txt',defaultextension='.txt')
        if path:
            try:Path(path).write_text('\n'.join('#'+str(e['id'])+' неделя '+str(e['week'])+' '+e['text']+' причины '+str(e['causes']) for e in self.world.state['events']),encoding='utf-8')
            except OSError as exc:messagebox.showerror('Экспорт',str(exc),parent=self)

    def error_report(self):
        path=save_dir()/'god-error-report.json'
        try:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps({'version':__version__,'os':platform.platform(),'week':self.world.state['week'],'error':self.last_error,'graphics':G.diagnostic()},ensure_ascii=False,indent=2),encoding='utf-8')
            messagebox.showinfo('Отчёт',str(path),parent=self)
        except OSError as exc:messagebox.showerror('Отчёт',str(exc),parent=self)

    def report_callback_exception(self,exc,value,tb):
        self.running=False;self.last_error=''.join(traceback.format_exception(exc,value,tb));messagebox.showerror('Ошибка',str(value)+'\nНажмите «Отчёт». Мир остановлен.',parent=self)

    def legacy(self):
        # One Tk interpreter per window/process. Launch a separate process, not nested Tk.
        import subprocess,sys
        self.running=False
        try:
            if getattr(sys,'frozen',False):subprocess.Popen([sys.executable,'--legacy'])
            else:subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[2]/'gorod_window.py'),'--legacy'])
        except OSError as exc:messagebox.showerror('Режим кандидата',str(exc),parent=self)

    def dispatch(self,op,payload):
        if self.link:
            if not self.net_connected or self.net_failed:raise RuleError('Нет соединения: общий мир остановлен. Отключите P2P для одиночного продолжения.')
            if self.net_busy:raise RuleError('Дождитесь ответа создателя')
            if not self.net_host:
                self.net_busy=True;self.link.send({'type':'god-command','revision':self.world.state['revision'],'op':op,'payload':payload});return
            packet=N.command(self.world,self.world.state['revision'],op,payload,delta=True);self.link.send({'type':'god-state','snapshot':packet});return
        if op=='plan':execute(self.world,parse(self.world,payload))
        elif op=='power':self.world.intervene(payload)
        elif op=='direct':self.world.direct(payload)
        elif op=='step':self.world.step(payload,True)
        elif op=='territory':self.world.territorial_action(payload['op'],payload['value'])
        elif op=='story':self.world.story_action(payload['op'],payload['value'])

    def poll_network(self):
        if self.link:
            for _ in range(20):
                try:msg=self.link.events.get_nowait()
                except queue.Empty:break
                try:
                    kind=msg.get('type')
                    if kind=='connected':
                        self.net_connected=self.net_host;self.net_failed=False
                        if self.net_host:self.link.send({'type':'god-state','snapshot':N.snapshot(self.world)})
                    elif kind=='god-resync' and self.net_host:self.link.send({'type':'god-state','snapshot':N.snapshot(self.world)})
                    elif kind=='god-command' and self.net_host:
                        try:packet=N.command(self.world,msg.get('revision'),msg.get('op'),msg.get('payload'),delta=True)
                        except (RuleError,DataError,KeyError,TypeError,ValueError) as exc:
                            self.link.send({'type':'god-reject','reason':str(exc),'snapshot':N.snapshot(self.world)})
                        else:self.link.send({'type':'god-state','snapshot':packet})
                        self.cancel();self.refresh()
                    elif kind in ('god-state','god-reject') and not self.net_host:
                        try:N.restore(self.world,msg['snapshot'])
                        except DataError:
                            if msg['snapshot'].get('format')=='god-shared-delta':self.link.send({'type':'god-resync'});self.running=False;continue
                            raise
                        self.net_busy=False;self.net_connected=True;self.cancel();self.refresh()
                        if kind=='god-reject':messagebox.showwarning('P2P',msg['reason'],parent=self)
                    elif kind in ('error','disconnected'):
                        self.net_failed=True;self.net_connected=False;self.net_busy=False;self.running=False
                        self.status.configure(text='P2P потерян. Мир остановлен. Можно сохранить и открыть новую связь.')
                except (RuleError,DataError,NetworkError,KeyError,TypeError,ValueError) as exc:
                    self.net_failed=True;self.running=False;self.last_error=str(exc);self.status.configure(text='Ошибка P2P: '+str(exc))
        self.after(100,self.poll_network)

    def network_menu(self):
        self.running=False
        if self.link:
            if messagebox.askyesno('P2P','Отключить связь? Друг сохранит последнее состояние.',parent=self):
                self.link.close();self.link=None;self.net_connected=False;self.net_failed=False;self.net_busy=False;self.refresh()
            return
        dlg=tk.Toplevel(self);dlg.title('Два бога — общий город без выделенного сервера');dlg.geometry('610x340')
        mode=tk.StringVar(value='host');ttk.Radiobutton(dlg,text='Создать связь для текущего мира',variable=mode,value='host').pack(anchor='w',padx=12,pady=6);ttk.Radiobutton(dlg,text='Подключиться (заменит локальный мир)',variable=mode,value='guest').pack(anchor='w',padx=12)
        fields={}
        for key,label,default in [('ip','IP создателя / VPN',''),('port','TCP-порт',str(DEFAULT_PORT)),('code','Код создателя',new_code())]:
            row=ttk.Frame(dlg);row.pack(fill='x',padx=12,pady=5);ttk.Label(row,text=label,width=23).pack(side='left');entry=ttk.Entry(row,width=40);entry.insert(0,default);entry.pack(side='left');fields[key]=entry
        ttk.Label(dlg,text='Оба игрока используют 0.8.9. Ход времени и операции проверяет создатель.\nДля интернета — VPN или проброс порта. Пакеты НЕ шифруются; только доверенные друзья.\nПродолжение: создатель загружает обычный сейв мира и открывает новый код.',wraplength=580).pack(padx=12,pady=8)
        def connect():
            try:
                port=int(fields['port'].get());code=fields['code'].get().strip()
                if not 1<=port<=65535:raise ValueError('Порт 1..65535')
                link=Link();self.net_host=mode.get()=='host';self.net_connected=False;self.net_failed=False;self.net_busy=False
                if self.net_host:link.host(code,fingerprint(self.world.data),port=port)
                else:link.join(fields['ip'].get().strip(),code,fingerprint(self.world.data),{'observer':'god'},port)
                self.link=link
            except (ValueError,NetworkError) as exc:messagebox.showerror('P2P',str(exc),parent=dlg);return
            self.status.configure(text='Ожидание друга / соединения. Не публикуйте код.');dlg.destroy()
        b=ttk.Frame(dlg);b.pack(pady=6);self._button(b,'Начать соединение',connect);self._button(b,'Скопировать код',lambda:(self.clipboard_clear(),self.clipboard_append(fields['code'].get())));self._button(b,'Отмена',dlg.destroy);dlg.grab_set()

    def close(self):
        self.running=False
        if self.link:self.link.close()
        for timer in self.tk.call('after','info'):
            self.after_cancel(timer)
        self.destroy()


def main():
    app=App(scenario='last_winter');app.tabs.select(app.frames['story']);app.mainloop()
