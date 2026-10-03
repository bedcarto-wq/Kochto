"""Three player skills (charm, eloquence, cunning) with a free starting pool.

New campaigns store the authoritative 0..100 values in state.world['skills'].
The legacy engine still reads eight 0..~17 skills, so they are derived from
the three new ones (value/6, i.e. 30 -> 5, the old default). Old saves without
state.world['skills'] keep working through the reverse mapping.
"""
from __future__ import annotations

SKILLS = ('charm', 'eloquence', 'cunning')
LABELS = {'charm': 'Обаяние', 'eloquence': 'Красноречие', 'cunning': 'Хитрость'}
POOL = 90
MAXIMUM = 100
KEY = 'skills'
# legacy skill -> contributing new skills (averaged)
LEGACY = {
    'charisma': ('charm',),
    'persuasion': ('eloquence',),
    'media': ('eloquence', 'charm'),
    'organization': ('charm', 'eloquence'),
    'administration': ('eloquence', 'cunning'),
    'connections': ('charm', 'cunning'),
    'stealth': ('cunning',),
    'security': ('cunning',),
}
SCALE = 6


class SkillError(ValueError):
    pass


def validate(allocation):
    if not isinstance(allocation, dict) or set(allocation) != set(SKILLS):
        raise SkillError('Нужно распределить очки между обаянием, красноречием и хитростью.')
    values = {}
    for key in SKILLS:
        value = allocation[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAXIMUM:
            raise SkillError(f'{LABELS[key]}: целое число от 0 до {MAXIMUM}.')
        values[key] = value
    total = sum(values.values())
    if total != POOL:
        raise SkillError(f'Нужно распределить ровно {POOL} очков (сейчас {total}).')
    return values


def parse(text):
    """'30 30 30' -> allocation in SKILLS order."""
    parts = text.replace(',', ' ').split()
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise SkillError('Введи три целых числа через пробел, например: 40 30 20.')
    return validate(dict(zip(SKILLS, map(int, parts))))


def apply(state, allocation):
    values = validate(allocation)
    state.world[KEY] = dict(values)
    for legacy, sources in LEGACY.items():
        setattr(state.player, legacy, round(sum(values[s] for s in sources) / len(sources) / SCALE))
    return values


def value(state, skill, legacy=None):
    """Authoritative 0..100 value; old saves are mapped from the legacy skill."""
    stored = state.world.get(KEY) if isinstance(state.world, dict) else None
    if isinstance(stored, dict) and skill in stored:
        return max(0, min(MAXIMUM, int(stored[skill])))
    if legacy is None:
        legacy = next(name for name, sources in LEGACY.items() if sources == (skill,))
    return max(0, min(MAXIMUM, int(getattr(state.player, legacy, 5)) * SCALE))


def describe(state):
    return ', '.join(f'{LABELS[s]} {value(state, s)}' for s in SKILLS)


def ask_console():
    print(f'\nРаспредели {POOL} очков между навыками (0–{MAXIMUM}, нули допустимы):')
    print('Обаяние — встречи и субботники; красноречие — интервью, обходы, обещания;')
    print('хитрость — петиции и скрытые/грязные ходы.')
    while True:
        try:
            text = input('Обаяние Красноречие Хитрость [30 30 30]: ').strip() or '30 30 30'
        except (EOFError, KeyboardInterrupt):
            return None
        try:
            return parse(text)
        except SkillError as exc:
            print(exc)


def ask_tk():
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title('Кочто — навыки персонажа')
    root.resizable(False, False)
    result = [None]
    variables = {key: tk.IntVar(value=30) for key in SKILLS}
    ttk.Label(root, text=f'Распредели ровно {POOL} очков. Нули допустимы.').grid(row=0, column=0, columnspan=2, padx=12, pady=10, sticky='w')
    hints = {'charm': 'встречи, субботники', 'eloquence': 'интервью, обходы, обещания', 'cunning': 'петиции, скрытые ходы'}
    for row, key in enumerate(SKILLS, 1):
        ttk.Label(root, text=f'{LABELS[key]} ({hints[key]})').grid(row=row, column=0, padx=12, pady=4, sticky='w')
        ttk.Spinbox(root, from_=0, to=MAXIMUM, width=6, textvariable=variables[key]).grid(row=row, column=1, padx=12)
    remaining = ttk.Label(root)
    remaining.grid(row=4, column=0, columnspan=2, padx=12, sticky='w')

    def current():
        try:
            return {key: int(variables[key].get()) for key in SKILLS}
        except (tk.TclError, ValueError):
            return None

    def refresh(*_):
        values = current()
        remaining.configure(text='Осталось: ' + (str(POOL - sum(values.values())) if values else '?'))

    def accept():
        try:
            values = current()
            if values is None:
                raise SkillError('Введи целые числа.')
            result[0] = validate(values)
            root.destroy()
        except SkillError as exc:
            messagebox.showerror('Навыки', str(exc), parent=root)

    for variable in variables.values():
        variable.trace_add('write', refresh)
    buttons = ttk.Frame(root)
    buttons.grid(row=5, column=0, columnspan=2, pady=10)
    ttk.Button(buttons, text='Начать', command=accept).pack(side='left', padx=4)
    ttk.Button(buttons, text='Отмена', command=root.destroy).pack(side='left', padx=4)
    refresh()
    root.mainloop()
    return result[0]
