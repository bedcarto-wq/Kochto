"""Movable/resizable panels for the Tk window (buttons are never removed).

The pure layout logic (default/normalize/move/toggle/load/save) works without
Tk and is unit-tested. ``install(ui_module, path)`` patches ``TkinterUI`` so the
three text panels live in a draggable ``PanedWindow`` and a «Панели» menu lets
the player reorder, hide/show and reset them. The command buttons, the quick
action row and the input line stay where they are and cannot be hidden.
"""
from __future__ import annotations

import json
from pathlib import Path

PANELS = ('left', 'center', 'right')
TITLES = {'left': 'Я', 'center': 'Лента и план', 'right': 'Власть'}
REQUIRED = ('center',)  # the feed/plan panel can be moved but never hidden
MIN_WIDTH = 120


def default_layout():
    return {'order': list(PANELS), 'hidden': [], 'sizes': {}}


def normalize(layout):
    layout = layout if isinstance(layout, dict) else {}
    order = [p for p in layout.get('order', []) if p in PANELS]
    order = list(dict.fromkeys(order)) + [p for p in PANELS if p not in order]
    hidden = [p for p in dict.fromkeys(layout.get('hidden', [])) if p in PANELS and p not in REQUIRED]
    sizes = {}
    for key, value in (layout.get('sizes') or {}).items():
        if key in PANELS and isinstance(value, (int, float)) and value > 0:
            sizes[key] = max(MIN_WIDTH, int(value))
    return {'order': order, 'hidden': hidden, 'sizes': sizes}


def move(layout, panel, step):
    layout = normalize(layout)
    order = layout['order']
    i = order.index(panel)
    j = max(0, min(len(order) - 1, i + step))
    order.insert(j, order.pop(i))
    return layout


def toggle(layout, panel):
    layout = normalize(layout)
    if panel in REQUIRED:
        return layout
    if panel in layout['hidden']:
        layout['hidden'].remove(panel)
    else:
        layout['hidden'].append(panel)
    return layout


def visible(layout):
    layout = normalize(layout)
    return [p for p in layout['order'] if p not in layout['hidden']]


def load(path):
    try:
        return normalize(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return default_layout()


def save(path, layout):
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalize(layout), ensure_ascii=False, indent=1), encoding='utf-8')
        return True
    except OSError:
        return False


# --- Tk integration -------------------------------------------------------
_ORIGINAL = {}


def _apply(self):
    for pane in list(self._paned.panes()):
        self._paned.forget(pane)
    widths = {'left': 300, 'center': 560, 'right': 300}
    for name in visible(self._layout):
        frame = self._frames[name]
        width = self._layout['sizes'].get(name, widths[name])
        self._paned.add(frame, minsize=MIN_WIDTH, width=width, stretch='always' if name == 'center' else 'never')
    self._panel_menu_refresh()


def _remember_sizes(self):
    try:
        for name in visible(self._layout):
            width = self._frames[name].winfo_width()
            if width > 1:
                self._layout['sizes'][name] = width
    except Exception:
        pass


def _change(self, layout):
    _remember_sizes(self)
    sizes = self._layout.get('sizes', {})
    self._layout = normalize({**layout, 'sizes': sizes})
    _apply(self)
    save(self._layout_path, self._layout)


def _menu_refresh(self):
    menu = self._panel_menu
    menu.delete(0, 'end')
    for name in self._layout['order']:
        title = TITLES[name]
        menu.add_command(label=f'← {title} левее', command=lambda n=name: _change(self, move(self._layout, n, -1)))
        menu.add_command(label=f'→ {title} правее', command=lambda n=name: _change(self, move(self._layout, n, 1)))
        if name not in REQUIRED:
            shown = name not in self._layout['hidden']
            menu.add_command(label=('Скрыть ' if shown else 'Показать ') + title,
                             command=lambda n=name: _change(self, toggle(self._layout, n)))
        menu.add_separator()
    menu.add_command(label='Сбросить раскладку', command=lambda: _reset(self))


def _reset(self):
    self._layout = default_layout()
    _apply(self)
    save(self._layout_path, self._layout)


def _build(self, action_titles):
    tk, ttk = self.tk, self.ttk
    top = ttk.Frame(self.root)
    top.pack(fill='x', padx=6, pady=4)
    self.header = ttk.Label(top, text='', font=('Segoe UI', 10, 'bold'))
    self.header.pack(side='left')
    for cmd, label in [('1', 'Я'), ('2', 'Партии'), ('3', 'Пресса'), ('4', 'Журнал'),
                       ('5', 'Справка'), ('6', 'Управление'), ('7', 'Город'), ('0', 'Завершить неделю')]:
        ttk.Button(top, text=label, command=lambda c=cmd: self.on_command(c)).pack(side='right', padx=2)
    panels = ttk.Menubutton(top, text='Панели')
    self._panel_menu = tk.Menu(panels, tearoff=0)
    panels['menu'] = self._panel_menu
    panels.pack(side='right', padx=6)
    self._panel_button = panels

    self._paned = tk.PanedWindow(self.root, orient='horizontal', sashrelief='raised', sashwidth=6)
    self._paned.pack(fill='both', expand=True, padx=6, pady=4)
    self._frames = {}
    for name in PANELS:
        frame = ttk.Frame(self._paned)
        ttk.Label(frame, text=TITLES[name]).pack(anchor='w')
        self._frames[name] = frame
    self.left = tk.Text(self._frames['left'], state='disabled', wrap='word', font=('Segoe UI', 9))
    self.center = tk.Text(self._frames['center'], wrap='word', font=('Segoe UI', 9))
    self.right = tk.Text(self._frames['right'], state='disabled', wrap='word', font=('Segoe UI', 9))
    for widget in (self.left, self.center, self.right):
        widget.pack(fill='both', expand=True)

    quick = ttk.Frame(self.root)
    quick.pack(fill='x', padx=6)
    for aid, title in (action_titles or [])[:14]:
        ttk.Button(quick, text=title, command=lambda a=aid: self.on_command('action:' + a)).pack(side='left', padx=1, pady=1)

    bottom = ttk.Frame(self.root)
    bottom.pack(fill='x', padx=6, pady=6)
    self.entry = ttk.Entry(bottom, font=('Segoe UI', 11))
    self.entry.pack(side='left', fill='x', expand=True, ipady=2)
    self.entry.bind('<Return>', lambda e: self._submit())
    self.entry.bind('<Up>', lambda e: self._history_step(-1))
    self.entry.bind('<Down>', lambda e: self._history_step(1))
    self._history = []
    self._hist_pos = 0
    ttk.Button(bottom, text='▶', command=self._submit).pack(side='left', padx=4)

    self._layout = load(self._layout_path)
    _apply(self)


def _close(self):
    _remember_sizes(self)
    save(self._layout_path, self._layout)
    _ORIGINAL['_close'](self)


def install(ui_module, path):
    cls = ui_module.TkinterUI
    if _ORIGINAL:
        uninstall(ui_module)
    _ORIGINAL.update({'_build': cls._build, '_close': cls._close, 'cls': cls})
    cls._layout_path = Path(path)
    cls._build = _build
    cls._close = _close
    cls._panel_menu_refresh = _menu_refresh
    return cls


def uninstall(ui_module=None):
    cls = _ORIGINAL.get('cls') or (ui_module and ui_module.TkinterUI)
    if cls and '_build' in _ORIGINAL:
        cls._build = _ORIGINAL['_build']
        cls._close = _ORIGINAL['_close']
        for name in ('_layout_path', '_panel_menu_refresh'):
            if name in cls.__dict__:
                delattr(cls, name)
    _ORIGINAL.clear()
