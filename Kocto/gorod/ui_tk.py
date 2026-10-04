"""Окно «Город помнит» (Tkinter). Запуск из папки Kocto:  python -m gorod.ui_tk

Тонкий слой над gorod.session.Session: вся логика хода там, здесь только отрисовка.
Старое окно игры (ui.py) не затронуто.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import engine as E
from .session import SLOT_RU, Session

SAVE_DIR = Path(__file__).resolve().parent.parent / "gorod_saves"
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Кочто — Город помнит")
        self.geometry("1180x760")
        self.session = Session()
        self.slot_vars = {}
        self._build()
        self.after(100, self.new_game)

    # ---------- раскладка ----------
    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=4)
        for text, cmd in (("Новая игра", self.new_game), ("Сохранить", self.save), ("Загрузить", self.load)):
            ttk.Button(top, text=text, command=cmd).pack(side="left", padx=2)
        self.header = ttk.Label(top, font=("Arial", 11, "bold"))
        self.header.pack(side="left", padx=12)

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
        self.forecast = ttk.Label(left)
        self.forecast.pack(anchor="w")
        self.threat = ttk.Label(left)
        self.threat.pack(anchor="w", pady=2)
        ttk.Label(left, text="Позиции", font=("Arial", 10, "bold")).pack(anchor="w", pady=(8, 0))
        self.positions = tk.Text(left, height=6, wrap="word")
        self.positions.pack(fill="x")
        ttk.Label(left, text="Обещания", font=("Arial", 10, "bold")).pack(anchor="w", pady=(8, 0))
        self.promises = tk.Listbox(left, height=7)
        self.promises.pack(fill="both", expand=True)

        tabs = ttk.Notebook(right)
        tabs.pack(fill="both", expand=True)
        self.press = tk.Text(tabs, wrap="word", font=("Georgia", 11))
        self.log = tk.Text(tabs, wrap="word")
        tabs.add(self.press, text="Газеты")
        tabs.add(self.log, text="Журнал хода")
        self.press.tag_configure("paper", font=("Georgia", 9, "italic"))
        self.press.tag_configure("head", font=("Georgia", 13, "bold"))

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=8, pady=6)
        ttk.Label(bottom, text=EXAMPLES, foreground="#666").pack(anchor="w")
        row = ttk.Frame(bottom)
        row.pack(fill="x", pady=2)
        self.entry = ttk.Entry(row, font=("Arial", 12))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.understand())
        ttk.Button(row, text="Понять", command=self.understand).pack(side="left", padx=4)
        ttk.Button(row, text="Завершить неделю", command=self.end_week).pack(side="left", padx=4)
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
        name, gender, skills = dlg.result
        try:
            self.session.new(name, gender, skills)
        except E.RuleError as exc:
            messagebox.showerror("Кандидат", str(exc))
            return
        self.press.delete("1.0", "end")
        self.log.delete("1.0", "end")
        self._log("Кампания началась. Выборы — на неделе " + str(self.session.state.next_election_week) + ".")
        self.cancel()
        self.refresh()

    def save(self):
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
            self.session.load(Path(path))
        except E.DataError as exc:
            messagebox.showerror("Загрузка", str(exc))
            return
        self._log("Загружено: " + path)
        self.cancel()
        self.refresh()

    def understand(self):
        if self.session.state is None or self.session.over:
            return
        text = self.entry.get().strip()
        if not text:
            return
        try:
            self._show(self.session.understand(text))
        except E.RuleError as exc:
            messagebox.showwarning("Ход", str(exc))

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
        for slot in view.get("missing", []):
            opts = self.session.options(slot)
            ttk.Label(self.slots, text=SLOT_RU[slot] + ":").pack(side="left")
            box = ttk.Combobox(self.slots, state="readonly", values=[lab for _, lab in opts], width=34)
            box.pack(side="left", padx=4)
            box.bind("<<ComboboxSelected>>", lambda e, s=slot, o=opts, b=box: self._pick(s, o[b.current()][0]))
        self.do_btn.configure(state="normal" if view.get("ready") else "disabled")

    def _pick(self, slot, value):
        self._show(self.session.set_slot(slot, value))

    def cancel(self):
        self.session.cancel()
        self.summary.configure(text="Напишите действие и нажмите «Понять».")
        for w in self.slots.winfo_children():
            w.destroy()
        self.do_btn.configure(state="disabled")

    def confirm(self):
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
        if self.session.state is None or self.session.over:
            return
        try:
            rep = self.session.end_week()
        except E.RuleError as exc:
            messagebox.showwarning("Неделя", str(exc))
            return
        for line in rep["lines"]:
            self._log(line)
        self.press.insert("1.0", "\n")
        for a in reversed(rep["articles"]):
            self.press.insert("1.0", a["lead"] + "\n\n")
            self.press.insert("1.0", a["headline"] + "\n", "head")
            self.press.insert("1.0", a["paper_name"] + " · неделя " + str(rep["week"]) + "\n", "paper")
        self.refresh()
        if rep["dead"]:
            messagebox.showinfo("Игра окончена", "Кандидат погиб. Город запомнит.")
        elif rep["election"]:
            e = rep["election"]
            messagebox.showinfo("Выборы", ("Победа" if e["won"] else "Поражение") + ": "
                                + str(e["player"]) + " против " + str(e["rival"]) + ". Игра продолжается.")

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


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
