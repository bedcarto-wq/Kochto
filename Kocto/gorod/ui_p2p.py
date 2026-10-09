"""Tk-only P2P controls. All network I/O is in p2p.Link background threads."""
from __future__ import annotations

import queue
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from . import engine as E
from .multiplayer import Match, candidate, fingerprint
from .p2p import Link, NetworkError, DEFAULT_PORT, new_code
from .paths import save_dir


class P2PMixin:
    def init_p2p(self):
        self.base_data = self.session.data
        self.link = None
        self.match = None
        self.player_id = 0
        self.net_busy = False
        self.net_disconnected = False
        self.net_report_week = 0
        self.net_seen_journal = 0
        self.protocol('WM_DELETE_WINDOW', self.close_app)
        self.after(100, self.poll_network)

    def close_app(self):
        if self.link:
            self.link.close()
        for timer in self.tk.call('after','info'):
            self.after_cancel(timer)
        self.destroy()

    def can_act(self):
        return self.link is None or (self.match is not None and not self.net_disconnected
                and not self.net_busy and not self.match.ended and self.match.turn == self.player_id
                and not self.match.ready[self.player_id])

    def leave_network(self):
        if self.link:
            if not messagebox.askyesno('P2P', 'Закрыть сетевую партию? Сначала сохраните её, если хотите продолжить.', parent=self):
                return False
            self.link.close()
        self.link = self.match = None
        self.net_busy = self.net_disconnected = False
        self.session.data = self.base_data
        self.groups.heading('r', text=self.base_data['rival']['forms']['im'])
        self.net_label.configure(text='Одиночная кампания')
        return True

    def p2p_dialog(self):
        if self.link:
            messagebox.showinfo('P2P', 'Чтобы открыть другую партию, сначала выберите «Новая игра».', parent=self)
            return
        if self.session.state is None:
            messagebox.showinfo('P2P', 'Сначала создайте своего кандидата.', parent=self)
            return
        dlg = tk.Toplevel(self)
        dlg.title('P2P · два кандидата')
        dlg.resizable(False, False)
        mode = tk.StringVar(value='host')
        address = tk.StringVar(value='')
        port = tk.StringVar(value=str(DEFAULT_PORT))
        code = tk.StringVar(value=new_code())
        for i, (val, lab) in enumerate((('host', 'Создать новую партию'), ('join', 'Подключиться к другу'), ('resume', 'Продолжить P2P-сохранение (создатель)'))):
            ttk.Radiobutton(dlg, text=lab, value=val, variable=mode).grid(row=i, column=0, columnspan=2, sticky='w', padx=16, pady=3)
        for row, text, var in ((3, 'IP друга / адрес VPN:', address), (4, 'TCP-порт:', port), (5, 'Код партии:', code)):
            ttk.Label(dlg, text=text).grid(row=row, column=0, sticky='w', padx=16, pady=4)
            ttk.Entry(dlg, textvariable=var, width=38).grid(row=row, column=1, padx=16, pady=4)
        ttk.Label(dlg, text='Создатель отправляет другу свой IP, порт и код.\nПри подключении вставьте код друга вместо нового.\nLAN / VPN: без выделенного сервера. Интернет: нужен VPN\nили проброс TCP-порта. Данные не шифруются; играйте с друзьями.\nЗакройте порт после игры. Не публикуйте код партии.',
                  justify='left').grid(row=6, column=0, columnspan=2, sticky='w', padx=16, pady=12)
        def start():
            try:
                number = int(port.get())
                if not 1 <= number <= 65535:
                    raise ValueError()
            except ValueError:
                messagebox.showerror('P2P', 'Порт должен быть от 1 до 65535.', parent=dlg)
                return
            if mode.get() == 'join' and not address.get().strip():
                messagebox.showerror('P2P', 'Введите IP создателя партии.', parent=dlg)
                return
            restored = None
            if mode.get() == 'resume':
                path = filedialog.askopenfilename(parent=dlg, initialdir=save_dir(), filetypes=[('P2P-партия', '*.p2p.json')])
                if not path:
                    return
                try:
                    restored = Match.load(self.base_data, path)
                except E.DataError as exc:
                    messagebox.showerror('P2P', str(exc), parent=dlg)
                    return
            if not messagebox.askyesno('P2P', 'Одиночная кампания будет заменена сетевой. Продолжить?', parent=dlg):
                return
            st = self.session.state
            self.net_candidate = candidate(st.player_name, st.gender, st.skills)
            self.net_restore = restored
            link = Link()
            try:
                if mode.get() == 'join':
                    self.player_id = 1
                    link.join(address.get().strip(), code.get().strip(), fingerprint(self.base_data), self.net_candidate, number)
                else:
                    self.player_id = 0
                    link.host(code.get().strip(), fingerprint(self.base_data), number)
            except (NetworkError, OSError, ValueError) as exc:
                link.close()
                messagebox.showerror('P2P', str(exc), parent=dlg)
                return
            self.link = link
            self.net_busy = self.net_disconnected = False
            self.net_report_week = self.net_seen_journal = 0
            self.match = None
            self.cancel()
            self.net_label.configure(text=('Жду друга · порт '+str(number)+' · код '+code.get().strip()) if self.player_id == 0 else 'Подключаюсь к другу…')
            self._log('P2P: ожидаю прямое соединение. Одиночные действия заблокированы.')
            self.week_btn.configure(state='disabled')
            dlg.destroy()
        def copy_code():
            dlg.clipboard_clear()
            dlg.clipboard_append(code.get().strip())
        ttk.Button(dlg, text='Скопировать код', command=copy_code).grid(row=8, column=0, columnspan=2, pady=(0, 12))
        ttk.Button(dlg, text='Начать соединение', command=start).grid(row=7, column=0, padx=16, pady=12)
        ttk.Button(dlg, text='Отмена', command=dlg.destroy).grid(row=7, column=1, padx=16, pady=12)
        dlg.grab_set()

    def poll_network(self):
        try:
            if self.link:
                for _ in range(16):
                    try:
                        event = self.link.events.get_nowait()
                    except queue.Empty:
                        break
                    self.handle_network(event)
        except (E.DataError, E.RuleError, NetworkError, ValueError, TypeError, KeyError, IndexError) as exc:
            if self.link:
                self.link.close()
            self.net_disconnected = True
            self.net_busy = False
            self.net_label.configure(text='P2P приостановлена: '+str(exc))
            self._log('P2P: '+str(exc))
            self.do_btn.configure(state='disabled')
            self.week_btn.configure(state='disabled')
        finally:
            self.after(100, self.poll_network)

    def handle_network(self, event):
        kind = event.get('type')
        if kind == 'listening':
            self._log('TCP-порт открыт. Если появится запрос брандмауэра, разрешите игру только в доверенной сети.')
        elif kind == 'rejected':
            self._log('Подключение отклонено: '+event['reason'])
        elif kind == 'disconnected':
            self.net_disconnected = True
            self.net_busy = False
            self.net_label.configure(text='Связь потеряна. Сохраните P2P-партию и создайте соединение заново.')
            self.do_btn.configure(state='disabled')
            self.week_btn.configure(state='disabled')
            self._log('P2P приостановлена: '+event['reason'])
        elif kind == 'connected':
            self.press.delete('1.0', 'end')
            self.log.delete('1.0', 'end')
            self.last_chart = None
            self.last_articles = []
            if self.player_id == 0:
                c = event['candidate']
                if not isinstance(c, dict) or set(c) != {'name', 'gender', 'skills'}:
                    raise NetworkError('Неверный кандидат гостя')
                E.new_game(self.base_data, c['name'], c['skills'], c['gender'])
                if self.net_restore:
                    # Restore the original identities / skills; a different guest must not
                    # silently take over somebody else's campaign.
                    original = self.net_restore.states[1]
                    if c['name'] != original.player_name or c['gender'] != original.gender or c['skills'] != original.skills:
                        raise E.RuleError('Для продолжения гость должен создать исходного кандидата с теми же навыками')
                    self.match = self.net_restore
                else:
                    self.match = Match(self.base_data, [self.net_candidate, c])
                self.broadcast_match()
                self.install_match(self.match)
            else:
                self.net_label.configure(text='Соединение установлено. Получаю город…')
        elif kind == 'command':
            if self.player_id != 0 or self.match is None:
                raise NetworkError('Неожиданная команда')
            self.apply_net_command(1, event)
        elif kind == 'state':
            if self.player_id != 1:
                raise NetworkError('Гость не может изменять город напрямую')
            m = Match.restore(self.base_data, event['match'])
            if self.match and m.revision < self.match.revision:
                raise NetworkError('Получено устаревшее состояние')
            self.net_busy = False
            if event.get('error'):
                self._log('Команда отклонена: '+event['error'])
            if event.get('actor') == self.player_id:
                for line in event.get('lines', []):
                    self._log(line)
            self.install_match(m)
        else:
            raise NetworkError('Неизвестное сетевое сообщение')

    def broadcast_match(self, actor=None, lines=None, error=None):
        self.link.send({'type': 'state', 'match': self.match.snapshot(), 'actor': actor, 'lines': lines or [], 'error': error})

    def install_match(self, match):
        self.match = match
        # Keep the Session instance for input mode, but replace the authoritative projection.
        self.session.state = match.states[self.player_id]
        self.session.data = match.scoped_data(self.player_id)
        self.cancel()
        rival = self.session.data['rival']['forms']['im']
        self.groups.heading('r', text=rival)
        self.net_label.configure(text=('P2P · партия окончена: кандидат погиб' if match.ended else
                                      ('P2P · ваш ход' if self.can_act() else 'P2P · ход: '+match.states[match.turn].player_name)))
        if len(match.journal) < self.net_seen_journal:
            self.net_seen_journal = 0
        for line in match.journal[self.net_seen_journal:]:
            self._log(line)
        self.net_seen_journal = len(match.journal)
        rep = match.reports[self.player_id]
        if rep and rep['week'] > self.net_report_week:
            self.net_report_week = rep['week']
            self.present_report(rep)
        self.refresh()
        self.week_btn.configure(state='normal' if self.can_act() else 'disabled')

    def apply_net_command(self, player, msg):
        error, lines = None, []
        try:
            lines = self.match.command(player, msg.get('revision'), msg.get('op'), msg.get('payload'))
        except E.RuleError as exc:
            error = str(exc)
        self.broadcast_match(player, lines, error)
        if player == self.player_id:
            for line in lines:
                self._log(line)
            if error:
                messagebox.showwarning('P2P', error, parent=self)
        self.install_match(self.match)

    def net_command(self, op, payload=None):
        if not self.can_act():
            messagebox.showinfo('P2P', 'Дождитесь своего хода или восстановления связи.', parent=self)
            return
        msg = {'type': 'command', 'revision': self.match.revision, 'op': op, 'payload': payload}
        try:
            if self.player_id == 0:
                self.apply_net_command(0, msg)
            else:
                self.link.send(msg)
                self.net_busy = True
                self.do_btn.configure(state='disabled')
                self.week_btn.configure(state='disabled')
        except NetworkError as exc:
            messagebox.showerror('P2P', str(exc), parent=self)

    def net_confirm(self):
        if self.session.pending is None:
            return
        if self.session.intent:
            self.net_command('plan', {'text': self.session.text, 'cards': [asdict(x.card) for x in self.session.intent.steps]})
        else:
            self.net_command('action', {'card': asdict(self.session.pending), 'text': self.session.text})
        self.entry.delete(0, 'end')

    def save_network(self):
        if self.match is None:
            messagebox.showinfo('P2P', 'Партия ещё не началась.', parent=self)
            return
        folder = save_dir()
        folder.mkdir(exist_ok=True)
        path = filedialog.asksaveasfilename(initialdir=folder, initialfile='city.p2p.json', defaultextension='.p2p.json',
                                            filetypes=[('P2P-партия', '*.p2p.json')])
        if path:
            self.match.save(Path(path))
            self._log('Сохранена вся P2P-партия. Продолжение: P2P → продолжить сохранение у создателя.')
