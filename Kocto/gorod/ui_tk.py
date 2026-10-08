"""Окно «Город помнит» (Tkinter). Запуск из папки Kocto:  python -m gorod.ui_tk

Тонкий слой над gorod.session.Session: вся логика хода там, здесь только отрисовка.
Старое окно игры (ui.py) не затронуто.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from . import engine as E
from .paths import save_dir
from .session import MODES, SLOT_RU, Session
from .ui_p2p import P2PMixin
from . import graphics as G
import json
import platform
import traceback
from datetime import datetime

if G.AVAILABLE:
    from PIL import ImageTk

SAVE_DIR = save_dir()
EXAMPLES = ("Примеры: «встретиться с пенсионерами», «пообещать заморозку тарифов за 4 недели», "
            "«дать интервью Голосу улицы против расширения завода», «нанять охрану»")


class NewGameDialog(tk.Toplevel):
    def __init__(self, master, pool: int):
        super().__init__(master)
        self.title("Новый кандидат")
        self.resizable(False, False)
        self.result = None
        self.pool = pool
        self.name = tk.StringVar(value="")
        self.gender = tk.StringVar(value="m")
        self.vals = {k: tk.IntVar(value=pool // 3) for k in ("charm", "eloquence", "cunning")}
        ttk.Label(self, text="Имя и фамилия:").grid(row=0, column=0, sticky="w", padx=10, pady=4)
        ttk.Entry(self, textvariable=self.name, width=28).grid(row=0, column=1, padx=10)
        g = ttk.Frame(self)
        g.grid(row=1, column=1, sticky="w", padx=10)
        ttk.Label(self, text="Пол:").grid(row=1, column=0, sticky="w", padx=10)
        ttk.Radiobutton(g, text="мужской", value="m", variable=self.gender).pack(side="left")
        ttk.Radiobutton(g, text="женский", value="f", variable=self.gender).pack(side="left")
        labels = {"charm": "Обаяние (встречи)", "eloquence": "Красноречие (заявления, обещания, интервью)",
                  "cunning": "Хитрость (совет, охрана)"}
        for i, (k, lab) in enumerate(labels.items(), 2):
            ttk.Label(self, text=lab).grid(row=i, column=0, sticky="w", padx=10, pady=2)
            ttk.Spinbox(self, from_=0, to=100, width=6, textvariable=self.vals[k]).grid(row=i, column=1, sticky="w", padx=10)
        self.left = ttk.Label(self)
        self.left.grid(row=5, column=0, columnspan=2, sticky="w", padx=10)
        for v in self.vals.values():
            v.trace_add("write", lambda *_: self._refresh())
        b = ttk.Frame(self)
        b.grid(row=6, column=0, columnspan=2, pady=8)
        ttk.Button(b, text="Начать", command=self._ok).pack(side="left", padx=4)
        ttk.Button(b, text="Отмена", command=self.destroy).pack(side="left", padx=4)
        self._refresh()
        self.grab_set()

    def _values(self):
        try:
            return {k: int(v.get()) for k, v in self.vals.items()}
        except (tk.TclError, ValueError):
            return None

    def _refresh(self):
        v = self._values()
        self.left.configure(text="Осталось очков: " + (str(self.pool - sum(v.values())) if v else "?"))

    def _ok(self):
        v = self._values()
        if not self.name.get().strip() or v is None or sum(v.values()) != self.pool:
            messagebox.showerror("Кандидат", "Нужны имя и ровно " + str(self.pool) + " очков навыков.", parent=self)
            return
        self.result = (self.name.get().strip(), self.gender.get(), v)
        self.destroy()


class App(P2PMixin, tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Кочто — Город помнит " + __version__)
        self.geometry("1180x860")
        self.minsize(1000, 760)
        self.last_articles = []
        self.last_paper_week = 0
        self.images = {}
        self.graphic_error = None
        self.scale_value = 1.0
        self.tk.call("tk", "scaling", 1.33333)
        self.session = Session()
        self.slot_vars = {}
        self._build()
        self.init_p2p()
        self.after(100, self.new_game)

    # ---------- раскладка ----------
    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=4)
        for text, cmd in (("Новая игра", self.new_game), ("Сохранить", self.save), ("Загрузить", self.load)):
            ttk.Button(top, text=text, command=cmd).pack(side="left", padx=2)
        ttk.Button(top, text="P2P с другом", command=self.p2p_dialog).pack(side="left", padx=2)
        ttk.Button(top, text="Отчёт об ошибке", command=self.error_report).pack(side="left", padx=2)
        statusrow = ttk.Frame(self)
        statusrow.pack(fill="x", padx=10)
        self.net_label = ttk.Label(statusrow, text="Одиночная кампания", wraplength=1100)
        self.net_label.pack(anchor="w")
        self.graphics_label = ttk.Label(statusrow, text="ИИ-иллюстрации · Pillow" if G.AVAILABLE else "Графика отключена: Pillow не установлен. Игра доступна в текстовом виде.", foreground="#666")
        self.graphics_label.pack(anchor="w")
        self.header = ttk.Label(statusrow, font=("Arial", 11, "bold"))
        self.header.pack(anchor="w", pady=4)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8)
        left = ttk.Frame(body, width=420)
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(right, weight=2)

        self.groups = ttk.Treeview(left, columns=("p", "r", "t"), height=4)
        self.groups.heading("#0", text="Группа")
        rival = self.session.data["rival"]["forms"]["im"]
        for c, t in (("p", "Вы"), ("r", rival), ("t", "Доверие")):
            self.groups.heading(c, text=t)
            self.groups.column(c, width=70, anchor="center")
        self.groups.pack(fill="x", pady=4)
        self.forecast = ttk.Label(left, wraplength=400)
        self.forecast.pack(anchor="w")
        self.threat = ttk.Label(left, wraplength=400)
        self.threat.pack(anchor="w", pady=2)
        ttk.Label(left, text="Позиции", font=("Arial", 10, "bold")).pack(anchor="w", pady=(8, 0))
        self.positions = tk.Text(left, height=6, wrap="word")
        self.positions.pack(fill="x")
        ttk.Label(left, text="Обещания", font=("Arial", 10, "bold")).pack(anchor="w", pady=(8, 0))
        self.promises = tk.Listbox(left, height=7)
        self.promises.pack(fill="both", expand=True)

        tabs = ttk.Notebook(right)
        tabs.pack(fill="both", expand=True)
        self.city_frame = ttk.Frame(tabs)
        self.city_canvas = tk.Canvas(self.city_frame, background="#f5f0e4", highlightthickness=0, height=280)
        self.city_canvas.pack(fill="both", expand=True)
        self.city_canvas.bind("<Configure>", lambda e: self.draw_city())
        self.portrait_row = ttk.Frame(self.city_frame)
        self.portrait_row.pack(fill="x", pady=8)
        self.portrait_widgets = []
        for i, name in enumerate(("Председатель совета", "Редактор газеты", "Пенсионеры", "Рабочие")):
            panel = ttk.Frame(self.portrait_row)
            panel.pack(side="left", expand=True, fill="both", padx=4)
            label = ttk.Label(panel, anchor="center")
            label.pack()
            ttk.Label(panel, text=name, anchor="center", wraplength=120).pack(fill="x")
            self.portrait_widgets.append(label)
        ttk.Label(self.city_frame, text="Условный вид города · персонажи вымышлены · показатели групп слева", wraplength=560).pack(pady=4)
        self.paper_frame = ttk.Frame(tabs)
        ttk.Button(self.paper_frame, text="Сохранить выпуск в PNG", command=self.export_newspaper).pack(anchor="e", padx=8, pady=4)
        scroll = ttk.Scrollbar(self.paper_frame, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.paper_canvas = tk.Canvas(self.paper_frame, background="#f5f0e4", highlightthickness=0, yscrollcommand=scroll.set)
        self.paper_canvas.pack(fill="both", expand=True)
        scroll.configure(command=self.paper_canvas.yview)
        self.paper_canvas.bind("<Configure>", lambda e: self.draw_newspaper())
        self.press = tk.Text(tabs, wrap="word", font=("Georgia", 11))
        self.log = tk.Text(tabs, wrap="word")
        self.chart = tk.Canvas(tabs, background="white")
        tabs.add(self.city_frame, text="Город")
        tabs.add(self.paper_frame, text="Выпуск газеты")
        tabs.add(self.press, text="Газеты — текст")
        tabs.add(self.chart, text="Выборы")
        tabs.add(self.log, text="Журнал хода")
        self.tabs = tabs
        self.chart.bind("<Configure>", lambda e: self.draw_chart())
        self.last_chart = None
        self.press.tag_configure("paper", font=("Georgia", 9, "italic"))
        self.press.tag_configure("head", font=("Georgia", 13, "bold"))

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", padx=8, pady=6, before=body)
        modes = ttk.Frame(bottom)
        modes.pack(fill="x")
        ttk.Label(modes, text="Ввод:").pack(side="left")
        self.mode = tk.StringVar(value="text")
        for key, label in MODES.items():
            ttk.Radiobutton(modes, text=label, value=key, variable=self.mode,
                            command=self.switch_mode).pack(side="left", padx=4)
        ttk.Button(modes, text="Выгрузить выученные фразы", command=self.export).pack(side="right")
        ttk.Label(bottom, text=EXAMPLES, foreground="#666", wraplength=950).pack(anchor="w")
        self.text_row = ttk.Frame(bottom)
        self.text_row.pack(fill="x", pady=2)
        self.entry = ttk.Entry(self.text_row, font=("Arial", 12))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.understand())
        ttk.Button(self.text_row, text="Понять", command=self.understand).pack(side="left", padx=4)
        self.card_row = ttk.Frame(bottom)
        ttk.Label(self.card_row, text="Действие:").pack(side="left")
        self.card_action = ttk.Combobox(self.card_row, state="readonly", width=30,
                                        values=[n for _, n in self.session.actions()])
        self.card_action.pack(side="left", padx=4)
        self.card_action.bind("<<ComboboxSelected>>", lambda e: self.manual())
        self.week_btn = ttk.Button(bottom, text="Завершить неделю", command=self.end_week)
        self.week_btn.pack(anchor="e")
        self.preview = ttk.LabelFrame(bottom, text="Понято как")
        self.preview.pack(fill="x", pady=4)
        self.summary = ttk.Label(self.preview, wraplength=1100, justify="left")
        self.summary.pack(anchor="w", padx=6)
        self.slots = ttk.Frame(self.preview)
        self.slots.pack(anchor="w", padx=6)
        btns = ttk.Frame(self.preview)
        btns.pack(anchor="w", padx=6, pady=4)
        self.do_btn = ttk.Button(btns, text="Выполнить", command=self.confirm, state="disabled")
        self.do_btn.pack(side="left")
        ttk.Button(btns, text="Отмена", command=self.cancel).pack(side="left", padx=4)

    # ---------- действия ----------
    def new_game(self):
        dlg = NewGameDialog(self, self.session.data["meta"]["skill_pool"])
        self.wait_window(dlg)
        if not dlg.result:
            if self.session.state is None:
                self.destroy()
            return
        if self.link and not self.leave_network():
            return
        name, gender, skills = dlg.result
        try:
            self.session.new(name, gender, skills)
        except E.RuleError as exc:
            messagebox.showerror("Кандидат", str(exc))
            return
        self.press.delete("1.0", "end")
        self.log.delete("1.0", "end")
        self.last_chart = None
        self.last_articles = []
        self.last_paper_week = 0
        self.week_btn.configure(state="normal")
        self._log("Кампания началась. Выборы — на неделе " + str(self.session.state.next_election_week) + ".")
        self.cancel()
        self.refresh()

    def save(self):
        if self.link:
            self.save_network()
            return
        if self.session.state is None:
            return
        SAVE_DIR.mkdir(exist_ok=True)
        path = filedialog.asksaveasfilename(initialdir=SAVE_DIR, defaultextension=".json",
                                            filetypes=[("Сохранения", "*.json")])
        if path:
            self.session.save(Path(path))
            self._log("Сохранено: " + path)

    def load(self):
        SAVE_DIR.mkdir(exist_ok=True)
        path = filedialog.askopenfilename(initialdir=SAVE_DIR, filetypes=[("Сохранения", "*.json")])
        if not path:
            return
        try:
            loaded = E.load_game(Path(path))
        except E.DataError as exc:
            messagebox.showerror("Загрузка", str(exc))
            return
        if self.link and not self.leave_network():
            return
        self.session.state = loaded
        self.session.cancel()
        self.week_btn.configure(state="normal")
        self._log("Загружено: " + path)
        self.last_articles = []
        self.last_chart = None
        self.cancel()
        self.refresh()

    def understand(self):
        if self.session.state is None or self.session.over:
            return
        text = self.entry.get().strip()
        if not text:
            return
        if self.mode.get() == "improver":
            text = self.choose_variant(text)
            if text is None:
                return
        try:
            self._show(self.session.understand(text))
        except E.RuleError as exc:
            messagebox.showwarning("Ход", str(exc))

    def choose_variant(self, text):
        variants = self.session.suggest(text)
        dlg = tk.Toplevel(self)
        dlg.title("Улучшатель текста")
        choice = tk.IntVar(value=0 if variants else -1)
        ttk.Label(dlg, text="Как отправить в игру?", font=("Arial", 10, "bold")).pack(anchor="w", padx=10, pady=6)
        ttk.Radiobutton(dlg, text="Свой текст: " + text, value=-1, variable=choice).pack(anchor="w", padx=10)
        for i, v in enumerate(variants):
            mark = "" if v["complete"] else "  (не хватает данных — уточните после)"
            ttk.Radiobutton(dlg, text=v["text"] + mark + "\n    → " + v["summary"], value=i,
                            variable=choice).pack(anchor="w", padx=10, pady=2)
        if not variants:
            ttk.Label(dlg, text="Улучшить не получилось — игра не поняла фразу.").pack(anchor="w", padx=10)
        result = [None]

        def ok():
            i = choice.get()
            result[0] = text if i < 0 else variants[i]["text"]
            dlg.destroy()
        b = ttk.Frame(dlg)
        b.pack(pady=8)
        ttk.Button(b, text="Отправить", command=ok).pack(side="left", padx=4)
        ttk.Button(b, text="Отмена", command=dlg.destroy).pack(side="left", padx=4)
        dlg.grab_set()
        self.wait_window(dlg)
        if result[0] and result[0] != text:
            self.entry.delete(0, "end")
            self.entry.insert(0, result[0])
        return result[0]

    def switch_mode(self):
        self.session.set_mode(self.mode.get())
        self.cancel()
        if self.mode.get() == "card":
            self.text_row.pack_forget()
            self.card_row.pack(fill="x", pady=2)
        else:
            self.card_row.pack_forget()
            self.text_row.pack(fill="x", pady=2)

    def manual(self):
        if self.session.state is None or self.session.over:
            return
        ids = [k for k, _ in self.session.actions()]
        self._show(self.session.manual(ids[self.card_action.current()]))

    def export(self):
        if self.session.state is None:
            return
        SAVE_DIR.mkdir(exist_ok=True)
        path = filedialog.asksaveasfilename(initialdir=SAVE_DIR, initialfile="learned_phrases.json",
                                            defaultextension=".json")
        if path:
            n = self.session.export_learned(Path(path))
            self._log("Выгружено фраз: " + str(n) + " → " + path)

    def _show(self, view: dict):
        for w in self.slots.winfo_children():
            w.destroy()
        self.slot_vars = {}
        lines = [view["summary"]]
        lines += ["· " + n for n in view["notes"]]
        lines += ["! " + w for w in view.get("warnings", [])]
        if view.get("ready"):
            lines.append("Шанс " + str(view["chance"]) + "% · стоимость " + str(view["cost"]))
        self.summary.configure(text="\n".join(lines))
        if view.get("ok"):
            names = [n for _, n in self.session.actions()]
            ids = [k for k, _ in self.session.actions()]
            ttk.Label(self.slots, text="действие:").pack(side="left")
            act = ttk.Combobox(self.slots, state="readonly", values=names, width=26)
            act.current(ids.index(view["action"]))
            act.pack(side="left", padx=4)
            act.bind("<<ComboboxSelected>>", lambda e, b=act: self._show(self.session.set_action(ids[b.current()])))
            if view["action"] == "promise":
                ttk.Label(self.slots, text="срок, нед.:").pack(side="left")
                dl = tk.IntVar(value=view["deadline"] or 4)
                sp = ttk.Spinbox(self.slots, from_=1, to=self.session.data["actions"]["promise"]["max_deadline"],
                                 width=4, textvariable=dl,
                                 command=lambda v=dl: self._show(self.session.set_deadline(int(v.get()))))
                sp.pack(side="left", padx=4)
        for slot in view.get("missing", []):
            opts = self.session.options(slot)
            ttk.Label(self.slots, text=SLOT_RU[slot] + ":").pack(side="left")
            box = ttk.Combobox(self.slots, state="readonly", values=[lab for _, lab in opts], width=34)
            box.pack(side="left", padx=4)
            box.bind("<<ComboboxSelected>>", lambda e, s=slot, o=opts, b=box: self._pick(s, o[b.current()][0]))
        self.do_btn.configure(state="normal" if view.get("ready") and self.can_act() else "disabled")

    def _pick(self, slot, value):
        self._show(self.session.set_slot(slot, value))

    def cancel(self):
        self.session.cancel()
        self.summary.configure(text="Напишите действие и нажмите «Понять».")
        for w in self.slots.winfo_children():
            w.destroy()
        self.do_btn.configure(state="disabled")

    def confirm(self):
        if self.link:
            self.net_confirm()
            return
        try:
            lines = self.session.confirm()
        except E.RuleError as exc:
            messagebox.showwarning("Ход", str(exc))
            return
        for line in lines:
            self._log(line)
        self.entry.delete(0, "end")
        self.cancel()
        self.refresh()

    def end_week(self):
        if self.link:
            self.net_command("ready")
            return
        if self.session.state is None or self.session.over:
            return
        try:
            rep = self.session.end_week()
        except E.RuleError as exc:
            messagebox.showwarning("Неделя", str(exc))
            return
        self.present_report(rep)

    def present_report(self, rep):
        self.last_articles = rep["articles"]
        self.last_paper_week = rep["week"]
        for line in rep["lines"]:
            self._log(line)
        self.press.insert("1.0", "\n")
        for a in reversed(rep["articles"]):
            self.press.insert("1.0", a["lead"] + "\n\n")
            self.press.insert("1.0", a["headline"] + "\n", "head")
            self.press.insert("1.0", a["paper_name"] + " · неделя " + str(rep["week"]) + "\n", "paper")
        if rep.get("chart"):
            self.last_chart = rep["chart"]
            self.tabs.select(self.chart)
        self.draw_newspaper()
        self.refresh()
        if rep.get("match_ended"):
            messagebox.showinfo("P2P окончена", "Один из кандидатов погиб. Город запомнит.")
        elif rep["dead"]:
            messagebox.showinfo("Игра окончена", "Кандидат погиб. Город запомнит.")
        elif rep["election"]:
            e = rep["election"]
            messagebox.showinfo("Выборы", ("Ничья" if e["player"] == e["rival"] else ("Победа" if e["won"] else "Поражение")) + ": "
                                + str(e["player"]) + " против " + str(e["rival"]) + ". Игра продолжается.")

    # ---------- диаграмма выборов ----------
    def draw_chart(self):
        c = self.chart
        c.delete("all")
        if self.session.state is None:
            return
        ch = self.last_chart or self.session.forecast_chart()
        w = max(c.winfo_width(), 600)
        y = 14
        c.create_text(12, y, anchor="w", text=ch["title"], font=("Arial", 14, "bold"))
        y += 28

        def section(title, rows, colors):
            nonlocal y
            c.create_text(12, y, anchor="w", text=title, font=("Arial", 11, "bold"))
            y += 22
            for label, values in rows:
                c.create_text(12, y + 9, anchor="w", text=label[:30], font=("Arial", 10))
                x0, full = 240, w - 330
                x = x0
                for v, col in zip(values, colors):
                    ln = full * v / 100.0
                    c.create_rectangle(x, y, x + ln, y + 18, fill=col, outline="")
                    x += ln
                c.create_text(x0 + full + 8, y + 9, anchor="w",
                              text=" / ".join(str(v) + "%" for v in values), font=("Arial", 10))
                y += 26
            y += 8

        section("Мэр", [(n, [p]) for n, p in ch["mayor"]], ["#3a7bd5"])
        section("По группам: " + ch["you"] + " (синий) / " + ch["rival"] + " (серый)",
                [(n, [p, r]) for n, p, r in ch["groups"]], ["#3a7bd5", "#b0b0b0"])
        section("Совет: доля голосов", [(n + " — мест " + str(k), [p]) for n, p, k in ch["council"]], ["#e08a1e"])
        c.create_text(12, y + 6, anchor="nw", text=ch["caption"], width=w - 24, font=("Arial", 10, "italic"))

    # ---------- отрисовка ----------
    def _log(self, line: str):
        self.log.insert("end", line + "\n")
        self.log.see("end")

    def refresh(self):
        st = self.session.status()
        self.header.configure(text="Неделя " + str(st["week"]) + " · действий " + str(st["actions_left"])
                              + " · деньги " + str(st["money"]) + " · узнаваемость " + str(st["awareness"])
                              + " · выборы на неделе " + str(st["next_election"]) + " · " + st["role"]
                              + (" · РАНЕН" if st["injured"] else "") + (" · ПОГИБ" if st["dead"] else ""))
        self.groups.delete(*self.groups.get_children())
        for g in st["groups"]:
            self.groups.insert("", "end", text=g["name"], values=(g["player"], g["rival"], g["trust"]))
        f = st["forecast"]
        self.forecast.configure(text="Прогноз голосов: вы " + str(f["player"]) + " · соперник " + str(f["rival"]))
        self.threat.configure(text="Угроза: " + st["threat_label"] + " (" + str(st["threat"]) + ") · охрана: "
                              + str(st["security"]), foreground="#b00" if st["threat"] >= 60 else "#000")
        self.positions.delete("1.0", "end")
        mine = "; ".join(p + ": " + s for p, s in st["positions"]) or "не заявлены"
        his = "; ".join(p + ": " + s for p, s in st["rival_positions"]) or "—"
        self.positions.insert("end", "Вы — " + mine + "\n" + self.session.data["rival"]["forms"]["im"] + " — " + his)
        self.promises.delete(0, "end")
        for p in st["promises"]:
            self.promises.insert("end", p)
        self.draw_chart()
        self.draw_city()
        self.draw_newspaper()
        self.week_btn.configure(state="normal" if self.can_act() and not self.session.over else "disabled")

    def graphic_failure(self, exc):
        self.graphic_error = str(exc)
        self.graphics_label.configure(text='Ошибка графики: '+str(exc)+'. Текстовая игра доступна.')

    def draw_city(self):
        c = self.city_canvas
        c.delete('all')
        if not G.AVAILABLE:
            c.create_text(24, 24, anchor='nw', text='Текстовый режим — установите Pillow для графики.', width=450)
            return
        try:
            w, h = max(c.winfo_width(), 100), max(c.winfo_height(), 80)
            im = G.city(w, h)
            self.images['city'] = ImageTk.PhotoImage(im, master=self)
            c.create_image(w//2, h//2, image=self.images['city'])
            for i, label in enumerate(self.portrait_widgets):
                self.images['portrait'+str(i)] = ImageTk.PhotoImage(G.portrait(i, min(100, int(90*self.scale_value))), master=self)
                label.configure(image=self.images['portrait'+str(i)])
        except E.DataError as exc:
            self.graphic_failure(exc)

    def draw_newspaper(self):
        c = self.paper_canvas
        c.delete('all')
        if not G.AVAILABLE:
            c.create_text(24, 24, anchor='nw', text='Газеты доступны во вкладке «Газеты — текст».', width=450)
            return
        try:
            width = max(480, c.winfo_width()-8)
            im = G.newspaper(self.last_articles, self.last_paper_week, width)
            self.images['newspaper'] = ImageTk.PhotoImage(im, master=self)
            c.create_image(0, 0, anchor='nw', image=self.images['newspaper'])
            c.configure(scrollregion=(0, 0, im.width, im.height))
        except E.DataError as exc:
            self.graphic_failure(exc)

    def export_newspaper(self):
        if not G.AVAILABLE:
            messagebox.showinfo('Газета', 'Для экспорта PNG установите Pillow.', parent=self)
            return
        path = filedialog.asksaveasfilename(defaultextension='.png', initialfile='Город-помнит-неделя-'+str(self.last_paper_week)+'.png', filetypes=[('PNG', '*.png')])
        if path:
            try:
                G.newspaper(self.last_articles, self.last_paper_week).save(path)
                self._log('Газетный выпуск сохранён: '+path)
            except (E.DataError, OSError) as exc:
                messagebox.showerror('Газета', str(exc), parent=self)

    def error_report(self, error=None):
        SAVE_DIR.mkdir(exist_ok=True)
        path = SAVE_DIR / ('error-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.txt')
        # No shared code, IP, credentials or campaign text in a diagnostic report.
        state = self.session.state
        report = {'version': __version__, 'python': platform.python_version(), 'os': platform.platform(),
                  'pillow': G.AVAILABLE, 'week': state.week if state else None,
                  'network': bool(self.link), 'network_disconnected': self.net_disconnected,
                  'graphics_error': self.graphic_error, 'error': error}
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        messagebox.showinfo('Отчёт об ошибке', 'Сохранён файл для отправки разработчику:\n'+str(path), parent=self)

    def report_callback_exception(self, exc_type, exc_value, tb):
        details = ''.join(traceback.format_exception(exc_type, exc_value, tb))
        try:
            self.error_report(details)
        except Exception:
            messagebox.showerror('Ошибка игры', str(exc_value), parent=self)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
