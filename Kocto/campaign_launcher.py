"""Default launcher with campaign selection and end-of-week checkpoints.

Keeps the existing engine API through a small, explicit session adapter.
Diagnostic entry points bypass the campaign menu. main.py remains available
for legacy diagnostics; Windows launchers and the exe use this entry point.
"""
from __future__ import annotations

import argparse
import random
import sys
import uuid
from pathlib import Path

from save_slots import SaveError, SaveStore

STATUS = {'alive': 'Активна', 'dead': 'Персонаж погиб',
          'broken': 'Повреждено', 'incompatible': 'Другая версия'}
ROLES = {'outsider': 'Без должности', 'candidate': 'Кандидат',
         'councilor': 'Депутат', 'mayor': 'Мэр'}


class CampaignSession:
    def __init__(self, engine, store: SaveStore, slot_id: str | None):
        self.engine = engine
        self.store = store
        self.slot_id = slot_id or uuid.uuid4().hex
        self.existing = slot_id is not None
        self.saved_week = None
        self.original = {}

    def load_game(self):
        if not self.existing:
            return None, None, None
        raw = self.store.load(self.slot_id)
        if raw.get('_schema') != self.engine.SCHEMA_TAG:
            raise SaveError('Эта версия состояния игры не поддерживается.')
        try:
            state = self.engine.models.game_from_dict(raw)
            note = self.engine._migrate_save(state)
            rng = self.engine.systems.rng_from_state(state.rng_state, state.seed)
        except (TypeError, ValueError, KeyError) as exc:
            raise SaveError('Состояние кампании повреждено; можно восстановить предыдущую неделю.') from exc
        if state.is_game_over and state.game_over_reason == 'death':
            raise SaveError('Персонаж погиб. Сохранение оставлено в списке; начни новую кампанию.')
        self.saved_week = state.week
        return state, rng, note

    def save_game(self, state, rng: random.Random):
        # The legacy engine calls save after many commands and on close.
        # The new contract writes only the initial state or a completed week.
        if state.week == self.saved_week:
            return
        if state.week_actions or state.actions_this_week:
            return
        if self.saved_week is not None and state.week < self.saved_week:
            raise SaveError('Нельзя сохранить кампанию поверх более поздней недели.')
        state.rng_state = self.engine.systems.rng_state_to_json(rng)
        payload = self.engine.models.game_to_dict(state)
        payload['_schema'] = self.engine.SCHEMA_TAG
        if not self.existing:
            self.store.create(payload, self.slot_id)
            self.existing = True
        else:
            self.store.save(self.slot_id, payload)
        self.saved_week = state.week

    def install(self):
        if self.original:
            raise RuntimeError('Campaign session is already installed')
        path = self.store._path(self.slot_id)
        for key in ('load_game', 'save_game', 'MEMORY_FILE', 'SAVE_FILE'):
            self.original[key] = getattr(self.engine, key)
        self.engine.load_game = self.load_game
        self.engine.save_game = self.save_game
        self.engine.MEMORY_FILE = self.store.root / (self.slot_id + '.memory.json')
        self.engine.SAVE_FILE = path

    def uninstall(self):
        for key, value in self.original.items():
            setattr(self.engine, key, value)
        self.original.clear()


def _loadable(store, info, validate=None):
    if info.status != 'alive':
        raise SaveError('Эта кампания недоступна для продолжения: ' + STATUS[info.status] + '.')
    payload = store.load(info.slot_id)
    if validate:
        validate(payload)
    return info.slot_id


def _latest(store):
    return next((info for info in store.list_slots() if info.status == 'alive'), None)


def select_console(store: SaveStore, validate=None):
    """Returns ('new'|'load'|'quit', slot_id). Deletion always asks again."""
    while True:
        items = store.list_slots()
        print('\nКочто — кампании')
        for index, info in enumerate(items, 1):
            print(f'{index}. {info.name} | неделя {info.week or "?"} | '
                  f'{ROLES.get(info.role, info.role)} | {info.saved_at} | {STATUS[info.status]}'
                  + (' | есть копия' if info.has_backup else ''))
        if (store.root.parent / 'save.json').exists():
            print('Сейв старого режима сохранён отдельно и не загружается новым меню.')
        print('n — новая; c — продолжить последнюю; l N — загрузить; d N — удалить; r N — восстановить копию; q — выйти')
        try:
            command = input('> ').strip().lower().split()
        except (EOFError, KeyboardInterrupt):
            return 'quit', None
        if command == ['n']:
            return 'new', None
        if command == ['q']:
            return 'quit', None
        try:
            if command == ['c']:
                info = _latest(store)
                if info is None:
                    print('Нет активных кампаний. Создай новую.')
                    continue
                return 'load', _loadable(store, info, validate)
            if len(command) != 2 or command[0] not in ('l', 'd', 'r'):
                print('Выбери команду меню.')
                continue
            index = int(command[1]) - 1
            if not 0 <= index < len(items):
                raise SaveError('Нет такого сохранения.')
            info = items[index]
            if command[0] == 'l':
                return 'load', _loadable(store, info, validate)
            question = ('Удалить кампанию и резервную копию' if command[0] == 'd'
                        else 'Вернуться к предыдущему сохранённому состоянию')
            answer = input(f'{question} «{info.name}»? Введи «да»: ').strip().lower()
            if answer != 'да':
                continue
            if command[0] == 'd':
                store.delete(info.slot_id, confirmed=True)
            else:
                previous = store.load_backup(info.slot_id)
                if validate:
                    validate(previous)
                store.restore(info.slot_id)
                print('Предыдущее состояние восстановлено.')
        except (SaveError, ValueError, OSError) as exc:
            print(str(exc))
        except (EOFError, KeyboardInterrupt):
            return 'quit', None


def select_tk(store: SaveStore, validate=None):
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title('Кочто — выбор кампании')
    root.geometry('920x420')
    root.minsize(640, 300)
    result = ['quit', None]
    ttk.Label(root, text='Выберите сохранение или начните новую кампанию.').pack(anchor='w', padx=12, pady=12)
    columns = ('name', 'week', 'role', 'date', 'status')
    frame = ttk.Frame(root)
    frame.pack(fill='both', expand=True, padx=12)
    tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
    scroll = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    for column, label, width in zip(columns, ('Имя', 'Неделя', 'Должность', 'Дата (UTC)', 'Состояние'), (210, 70, 120, 220, 150)):
        tree.heading(column, text=label)
        tree.column(column, width=width, minwidth=50)
    tree.pack(side='left', fill='both', expand=True)
    scroll.pack(side='right', fill='y')
    items = {}

    def refresh():
        tree.delete(*tree.get_children())
        items.clear()
        for info in store.list_slots():
            items[info.slot_id] = info
            tree.insert('', 'end', iid=info.slot_id, values=(info.name, info.week or '?',
                        ROLES.get(info.role, info.role), info.saved_at, STATUS[info.status]))
        latest = _latest(store)
        if latest:
            tree.selection_set(latest.slot_id)

    def chosen():
        selection = tree.selection()
        if not selection:
            raise SaveError('Выбери сохранение в списке.')
        return items[selection[0]]

    def finish(mode, slot_id=None):
        result[:] = [mode, slot_id]
        root.destroy()

    def load(continue_latest=False):
        try:
            info = _latest(store) if continue_latest else chosen()
            if info is None:
                raise SaveError('Нет активной кампании. Начни новую.')
            slot_id = _loadable(store, info, validate)
            finish('load', slot_id)
        except (SaveError, OSError, ValueError) as exc:
            messagebox.showerror('Не удалось загрузить', str(exc), parent=root)

    def delete():
        try:
            info = chosen()
            if messagebox.askyesno('Удаление кампании', f'Удалить «{info.name}» и её резервную копию? Это нельзя отменить.', parent=root):
                store.delete(info.slot_id, confirmed=True)
                refresh()
        except (SaveError, OSError, ValueError) as exc:
            messagebox.showerror('Сохранения', str(exc), parent=root)

    def recover():
        try:
            info = chosen()
            previous = store.load_backup(info.slot_id)
            if validate:
                validate(previous)
            if messagebox.askyesno('Восстановление', f'Вернуть «{info.name}» к неделе {previous["week"]}? Текущее состояние будет заменено.', parent=root):
                store.restore(info.slot_id)
                refresh()
        except (SaveError, OSError, ValueError) as exc:
            messagebox.showerror('Сохранения', str(exc), parent=root)

    buttons = ttk.Frame(root)
    buttons.pack(fill='x', padx=12, pady=12)
    for label, callback in (('Новая игра', lambda: finish('new')),
                            ('Продолжить', lambda: load(True)), ('Загрузить', load),
                            ('Восстановить копию', recover), ('Удалить', delete), ('Выйти', lambda: finish('quit'))):
        ttk.Button(buttons, text=label, command=callback).pack(side='left', padx=3)
    if (store.root.parent / 'save.json').exists():
        ttk.Label(root, text='Сейв старого режима сохранён отдельно; новая система его не загружает.').pack(anchor='w', padx=12)
    ttk.Label(root, text='Автосохранение — после завершения недели. Незавершённый план не сохраняется.').pack(anchor='w', padx=12, pady=(0, 12))
    tree.bind('<Double-1>', lambda event: load())
    root.protocol('WM_DELETE_WINDOW', lambda: finish('quit'))
    refresh()
    root.mainloop()
    return tuple(result)


def run() -> int:
    import main as engine

    if any(flag in sys.argv[1:] for flag in ('--selftest', '--replay', '--debug-parser')):
        return engine.run()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--new', action='store_true')
    parser.add_argument('--slot')
    args, remaining = parser.parse_known_args(sys.argv[1:])
    store = SaveStore(engine.SAVE_DIR / 'campaigns')

    def validate(payload):
        if payload.get('_schema') != engine.SCHEMA_TAG:
            raise SaveError('Сохранение другой версии игры.')
        try:
            engine.models.game_from_dict(payload)
        except (TypeError, ValueError, KeyError) as exc:
            raise SaveError('Состояние кампании повреждено. Попробуй резервную копию.') from exc

    try:
        if args.new and args.slot:
            raise SaveError('Нельзя одновременно выбрать новую игру и сохранение.')
        if args.slot:
            info = next((info for info in store.list_slots() if info.slot_id == args.slot), None)
            if info is None:
                raise SaveError('Сохранение не найдено.')
            mode, slot_id = 'load', _loadable(store, info, validate)
        elif args.new:
            mode, slot_id = 'new', None
        else:
            use_tk = '--console' not in remaining and engine.ui.tk_available()
            mode, slot_id = (select_tk if use_tk else select_console)(store, validate)
        if mode == 'quit':
            return 0
        allocation = None
        if mode == 'new':
            import skills
            gui = '--console' not in remaining and engine.ui.tk_available()
            allocation = skills.ask_tk() if gui else skills.ask_console()
            if allocation is None:
                return 0
        session = CampaignSession(engine, store, slot_id)
        original_args = sys.argv[:]
        session.install()
        semantic = None
        try:
            from campaign_play import PlayRuntime
            semantic = PlayRuntime.from_file(engine, engine.DATA_DIR / 'world' / 'semantic.json', allocation)
            semantic.install()
            sys.argv = [original_args[0]] + remaining
            return engine.run()
        finally:
            sys.argv = original_args
            if semantic is not None:
                semantic.uninstall()
            session.uninstall()
    except (SaveError, OSError, ValueError) as exc:
        engine._fatal('Не удалось открыть кампанию: ' + str(exc))
        if not engine.models.frozen_build():
            print(str(exc))
        return 1


if __name__ == '__main__':
    sys.exit(run())
