from __future__ import annotations

import textwrap
from typing import Any, Callable, Dict, List, Optional, Tuple

from models import ElectoralSystem, GameState, PrisonStatus, Role, WEEKLY_ACTION_LIMIT

LINE = "=" * 78
THIN = "-" * 39
MENU_HINT = "Меню: 1=Я 2=Партии 3=Пресса 4=Журнал 5=Справка 6=Управление 7=Город 0=Завершить неделю"

PRISON_LABEL = {
    PrisonStatus.FREE: "на свободе",
    PrisonStatus.UNDER_INVESTIGATION: "под следствием",
    PrisonStatus.TRIAL: "суд",
    PrisonStatus.PRISON: "в тюрьме",
    PrisonStatus.DETAINED: "задержан",
    PrisonStatus.ARRESTED: "под арестом",
    PrisonStatus.ESCAPED: "в бегах",
    PrisonStatus.FUGITIVE: "в розыске",
}


def wrap(text: str, width: int = 72) -> List[str]:
    return textwrap.wrap(text, width=width) or [""]


def _src_tag(item: Dict[str, Any], state: GameState) -> str:
    if getattr(state, "detail_level", "нормально") != "полно":
        return ""
    src = item.get("source", "gen")
    return " [" + str(src) + "]"


def _share(state: GameState, subject_id: str, kind: str) -> float:
    pop = int(getattr(state.village, "population", 0) or 0)
    if pop <= 0:
        return 0.0
    total = 0
    for g in state.groups:
        bucket = g.candidate_support if kind == "candidate" else g.party_support
        total += int(bucket.get(subject_id, 0))
    return round(total / pop * 100.0, 1)


def _loc(state: GameState) -> str:
    return str(getattr(state.village, "display_name", state.village.name))


def _party_name(state: GameState, pid: str) -> str:
    for p in state.parties:
        if p.id == pid:
            return p.name
    return pid


def _action_title(action_id: str) -> str:
    return action_id


# ================= рендер =================
def render_header(state: GameState) -> str:
    wk = state.current_week
    money = state.player.money
    treas = state.treasury
    threat = int(state.player.threat)
    system = state.electoral_system.value
    role = state.player.role.value
    acts = state.actions_this_week
    return (f"Неделя {wk} | Локация: {_loc(state)} | Деньги {money} | Казна {treas} | "
            f"Угроза {threat} | Система: {system} | Роль: {role} | "
            f"Действия: {acts}/{WEEKLY_ACTION_LIMIT}\n{MENU_HINT}")


def render_left(state: GameState) -> str:
    pl = state.player
    pname = _party_name(state, pl.party_id) if pl.party_id else "—"
    lines = ["── Я ──",
             f"Имя: {pl.name} ({pl.age})",
             f"Роль: {pl.role.value}",
             f"Партия: {pname} ({pl.party_role or '—'})",
             f"Деньги: {pl.money}",
             f"Здоровье: {pl.health} | Стресс: {pl.stress} | Усталость: {pl.fatigue}",
             f"Узнаваемость: {pl.awareness} | Доверие: {pl.trust} | Анти: {pl.anti_awareness}",
             f"Улики: {pl.evidence} | Следствие: {pl.investigation} | Угроза: {pl.threat}",
             f"Побег (подготовка): {pl.escape_prep}",
             f"Статус: {PRISON_LABEL.get(pl.prison_status, pl.prison_status.value)}"]
    if pl.legacy_tags:
        lines.append("Наследие: " + ", ".join(pl.legacy_tags[-5:]))
    return "\n".join(lines) + "\n"


def _budget(state: GameState) -> Tuple[int, int]:
    try:
        import systems
        b = systems.budget_info(state)
        return int(b["income"]), int(b["expenses"])
    except Exception:
        return 120 + state.council_seats * 12, 80 + len(state.promises) * 3


def render_right(state: GameState) -> str:
    lines = ["── Фракции / власть ──"]
    income, expenses = _budget(state)
    lines.append(f"Казна: {state.treasury} | Доход/нед: {income} | Расход/нед: {expenses}")
    lines.append(f"Мест в совете (игрок): {state.council_seats}")
    lines.append(f"Следующие выборы: нед. {state.next_election_week} (прошло: {state.election_count})")
    lines.append("")
    lines.append("Партии:")
    for p in state.parties:
        sh = _share(state, p.name, "party")
        lines.append(f"  · {p.name}: поп. {p.popularity} доверие {p.trust_to_player} "
                     f"места {p.seats} поддержка {sh}%")
    psh = _share(state, state.player.name, "candidate")
    lines.append(f"  · Игрок ({state.player.name}): узнав. {state.player.awareness} "
                 f"доверие {state.player.trust} поддержка {psh}%")
    lines.append("")
    lines.append("Места парламента:")
    for pid, seats in sorted(state.parliament_seats.items(), key=lambda kv: kv[1], reverse=True):
        nm = _party_name(state, pid) if pid != "player" else state.player.name
        lines.append(f"  {nm}: {seats}")
    return "\n".join(lines) + "\n"


def render_center(state: GameState, message: str) -> str:
    lines: List[str] = []
    if message:
        for m in wrap(message, 76):
            lines.append(">> " + m)
        lines.append("")
    if state.week_actions:
        lines.append("── План недели (резолв в конце; «отменить N» — убрать) ──")
        try:
            import systems
            plan = systems.plan_lines(state)
        except Exception:
            plan = [str(qa.get("action_id", "")) + (" [отложено]" if qa.get("delayed") else "")
                    for qa in state.week_actions]
        for row in plan:
            for i, w in enumerate(wrap(row, 74)):
                lines.append(("  · " if i == 0 else "    ") + w)
        lines.append("")
    lines.append("── Лента прессы ──")
    feed = list(state.news_feed)[-8:]
    if not feed:
        lines.append("  (пусто)")
    for item in feed:
        head = item.get("headline", "")
        tone = float(item.get("tone", 0.0))
        pub = item.get("publication", "")
        wk = item.get("week", "?")
        no = item.get("archive_no", "?")
        prefix = f"  [№{no}] [{wk}] {pub} | тон {tone:+.2f}" + _src_tag(item, state)
        lines.append(prefix)
        for w in wrap(head, 72):
            lines.append("    " + w)
        if getattr(state, "detail_level", "нормально") == "полно":
            td = item.get("tier_distribution") or {}
            tv = item.get("tone_vector") or {}
            if td:
                lines.append("    тир-вектор: " + str(td))
            if tv:
                lines.append("    тон-вектор: " + str(tv))
    lines.append("")
    lines.append(MENU_HINT)
    return "\n".join(lines) + "\n"


def render_main(state: GameState, message: str) -> str:
    return "\n".join([LINE, render_header(state), LINE,
                      render_left(state), THIN, render_right(state), THIN,
                      render_center(state, message), LINE]) + "\n"


# ================= модалки =================
def _modal_me(state: GameState) -> str:
    pl = state.player
    lines = [LINE, "ЭКРАН: Я (навыки)", LINE]
    skills = [("Харизма", pl.charisma), ("Убеждение", pl.persuasion), ("Организация", pl.organization),
              ("Медиа", pl.media), ("Администрирование", pl.administration), ("Скрытность", pl.stealth),
              ("Связи", pl.connections), ("Безопасность", pl.security)]
    for name, val in skills:
        lines.append(f"  {name:<18} {val:>3}")
    lines.append("")
    lines.append(render_left(state))
    return "\n".join(lines) + "\n"


def _modal_parties(state: GameState) -> str:
    return "\n".join([LINE, "ЭКРАН: ПАРТИИ", LINE, render_right(state)]) + "\n"


def _modal_press(state: GameState) -> str:
    lines = [LINE, "ЭКРАН: ПРЕССА", LINE, "Издания:"]
    for pub in state.publications:
        lines.append(f"  · {pub.name}: тон {pub.tone:+.2f} охват {pub.reach}")
    lines.append("")
    lines.append("Архив вырезок:")
    for item in list(state.clippings)[-15:]:
        head = item.get("headline", "")
        tone = float(item.get("tone", 0.0))
        pub = item.get("publication", "")
        wk = item.get("week", "?")
        no = item.get("archive_no", "?")
        lines.append(f"  [№{no}] [{wk}] {pub} | тон {tone:+.2f}" + _src_tag(item, state))
        for w in wrap(head, 72):
            lines.append("    " + w)
        for w in wrap(item.get("body", ""), 72):
            lines.append("      " + w)
        lines.append("")
    return "\n".join(lines) + "\n"


def _modal_log(state: GameState) -> str:
    return "\n".join([LINE, "ЭКРАН: ЖУРНАЛ", LINE] + state.event_log[-50:]) + "\n"


def _modal_gov(state: GameState) -> str:
    income, expenses = _budget(state)
    lines = [LINE, "ЭКРАН: УПРАВЛЕНИЕ (бюджет, законы, обещания)", LINE,
             f"Казна: {state.treasury} | Доход/нед: {income} | Расход/нед: {expenses} | Баланс: {income - expenses:+}",
             "", "Законопроекты:"]
    if not state.bills:
        lines.append(" нет активных")
    for bill in state.bills:
        lines.append(f" [{bill.get('stage','?')}] {bill.get('title','')}")
    lines += ["", "Принятые законы:"]
    if not state.enacted_laws:
        lines.append(" нет")
    for law in state.enacted_laws[-15:]:
        lines.append(f"  {law.get('id','')} (нед. {law.get('enacted_week','?')}, стоимость/нед {law.get('weekly_cost',0)})")
    lines += ["", "Обещания:"]
    if not state.promises:
        lines.append(" нет")
    for pr in state.promises:
        lines.append(f" [{pr.get('status','?')}] {pr.get('text','')} (до нед. {pr.get('deadline_week','?')}, прогресс {int(pr.get('progress',0))})")
    lines.append(LINE)
    return "\n".join(lines) + "\n"


def _modal_help(state: GameState) -> str:
    lines = [LINE, "СПРАВКА", LINE,
             "0 или пустой ввод — завершить неделю.",
             "1 — Я, 2 — Партии, 3 — Пресса, 4 — Журнал, 5 — Справка, 6 — Управление.",
             "Команды: выбор N · детализация кратко|нормально|полно · память очистить · преодолеть вето",
             "Свободный закон: «внеси закон <текст>».",
             "План: «отменить N» — убрать действие из плана и вернуть деньги. 7 — Город и соперники.",
             "Отзыв автору: «отзыв <текст>» — сохраняется в файл, его можно прислать.",
             "", "Можно писать что угодно своими словами, например:"]
    for ex in _EXAMPLES:
        lines.append("  «" + ex + "»")
    lines += ["Если фраза не подходит под готовое действие, она станет «своим действием»:",
              "шанс и цена считаются по смыслу (тайно, деньги, СМИ, атака, обещание, разведка...).",
              "", "Готовые действия:"]
    for aid, title in _HELP_ACTIONS:
        lines.append("  · " + str(title) + " [" + str(aid) + "]")
    lines.append(LINE)
    return "\n".join(lines) + "\n"


_HELP_ACTIONS: List[Tuple[str, str]] = []
_EXAMPLES: List[str] = []


def set_examples(examples: List[str]) -> None:
    global _EXAMPLES
    _EXAMPLES = [str(x) for x in (examples or [])]


def _modal_world(state: GameState) -> str:
    try:
        import systems
        body = systems.world_report(state)
    except Exception as exc:
        body = ["Нет данных о городе: " + str(exc)]
    return "\n".join([LINE, "ЭКРАН: ГОРОД И СОПЕРНИКИ", LINE] + body + [LINE]) + "\n"


def set_help_actions(titles: List[Tuple[str, str]]) -> None:
    global _HELP_ACTIONS
    _HELP_ACTIONS = list(titles or [])


def _modal_gameover(state: GameState) -> str:
    pl = state.player
    reason = state.game_over_reason or "неизвестно"
    lines = [LINE, "ИГРА ЗАВЕРШЕНА", LINE,
             f"Причина: {reason}",
             f"Недель прожито: {state.week}",
             f"Выборов пройдено: {state.election_count}",
             f"Итоговая роль: {pl.role.value}",
             f"Наследие: {', '.join(pl.legacy_tags) if pl.legacy_tags else '—'}",
             LINE]
    return "\n".join(lines) + "\n"


_MODAL_MAP: Dict[str, Callable[[GameState], str]] = {
    "me": _modal_me, "parties": _modal_parties, "press": _modal_press,
    "log": _modal_log, "gov": _modal_gov, "help": _modal_help, "world": _modal_world, "gameover": _modal_gameover,
}


def render_modal(kind: str, state: GameState) -> str:
    fn = _MODAL_MAP.get(kind)
    if fn is None:
        return "Неизвестный экран: " + str(kind)
    return fn(state)


# ================= ревизия / выбор =================
def render_review(review: List[Dict[str, Any]], ask: bool = True) -> str:
    lines = [LINE, "РЕВИЗИЯ НЕДЕЛИ — похоже ли то, что произошло?" if ask else "ИТОГИ ДЕЙСТВИЙ НЕДЕЛИ", LINE]
    if not review:
        lines.append("(нет событий для ревизии)")
        return "\n".join(lines) + "\n"
    for item in review:
        idx = item.get("index", "?")
        title = item.get("title", "")
        tier = item.get("tier", "")
        lines.append("")
        if tier in ("resolved", ""):
            lines.append(f"[{idx}] {title}")
        elif tier == "cancelled":
            lines.append(f"[{idx}] {title} — отменено")
        else:
            lines.append(f"[{idx}] {title} — исход: {tier}")
        script = item.get("script", {}) or {}
        for w in wrap(str(script.get("primary", "")), 74):
            lines.append("    " + w)
        for sec in script.get("secondary", []) or []:
            for w in wrap(str(sec), 74):
                lines.append("      · " + w)
        text = item.get("text") or {}
        if not text and tier == "resolved":
            lines.append("    (тайно — в газеты не попало)")
        if text:
            lines.append("    — вырезка —")
            for w in wrap(str(text.get("headline", "")), 72):
                lines.append("      " + w)
            if text.get("lead"):
                for w in wrap(str(text.get("lead", "")), 72):
                    lines.append("      " + w)
            for w in wrap(str(text.get("body", "")), 72):
                lines.append("      " + w)
        if ask:
            lines.append("    похоже? (да/нет) · если нет — что не так (строкой)")
    lines.append("")
    lines.append(LINE)
    return "\n".join(lines) + "\n"


def render_choices(options: List[Tuple[str, str]]) -> str:
    lines = ["Возможные трактовки (выбор N):"]
    for i, (aid, title) in enumerate(options, 1):
        lines.append(f"  {i}) {title}  [{aid}]")
    return "\n".join(lines)


def _prop_line(prop: Dict[str, Any]) -> str:
    if not prop:
        return "—"
    intent = prop.get("intent", "?")
    aid = prop.get("id", "?")
    target = prop.get("target", "")
    conf = prop.get("confidence", 0.0)
    try:
        conf_f = float(conf)
    except (TypeError, ValueError):
        conf_f = 0.0
    tgt = " → " + str(target) if target else ""
    return f"{aid} ({intent}){tgt}, увер. {conf_f:.2f}"


def render_ab_choices(ab_proposals: List[Dict[str, Any]], state: GameState) -> str:
    lines = ["Два распознавателя предложили варианты — выбери, кто точнее (выбор N):"]
    counter = 1
    for pair in ab_proposals:
        parser_prop = (pair or {}).get("parser") or {}
        nn_prop = (pair or {}).get("nn") or {}
        lines.append(f"  {counter}) парсер: " + _prop_line(parser_prop))
        counter += 1
        lines.append(f"  {counter}) нейросеть: " + _prop_line(nn_prop))
        counter += 1
    return "\n".join(lines)


# ================= Tkinter =================
def tk_available() -> bool:
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def ask_profile() -> Tuple[str, int]:
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.withdraw()
    holder = {"name": "Игрок", "age": 35, "done": False}
    win = tk.Toplevel(root)
    win.title("Новая кампания")
    win.geometry("320x170")
    win.transient(root)
    win.grab_set()
    ttk.Label(win, text="Имя персонажа:").pack(anchor="w", padx=10, pady=(10, 0))
    name_var = tk.StringVar(value="Игрок")
    ttk.Entry(win, textvariable=name_var, width=30).pack(anchor="w", padx=10)
    ttk.Label(win, text="Возраст:").pack(anchor="w", padx=10, pady=(6, 0))
    age_var = tk.StringVar(value="35")
    ttk.Entry(win, textvariable=age_var, width=10).pack(anchor="w", padx=10)

    def submit() -> None:
        holder["name"] = (name_var.get().strip() or "Игрок")
        try:
            holder["age"] = int(age_var.get().strip() or "35")
        except ValueError:
            holder["age"] = 35
        holder["done"] = True
        win.destroy()

    ttk.Button(win, text="Начать", command=submit).pack(pady=10)
    win.protocol("WM_DELETE_WINDOW", submit)
    root.wait_window(win)
    root.destroy()
    return holder["name"], holder["age"]


class TkinterUI:
    def __init__(self, action_titles: List[Tuple[str, str]],
                 on_command: Callable[[str], None],
                 on_close: Callable[[], None]) -> None:
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.ttk = ttk
        self.on_command = on_command
        self.on_close = on_close
        set_help_actions(action_titles)
        self.root = tk.Tk()
        self.root.title("Кочто")
        self.root.geometry("1180x760")
        self._build(action_titles)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self, action_titles: List[Tuple[str, str]]) -> None:
        tk = self.tk
        ttk = self.ttk
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=6, pady=4)
        self.header = ttk.Label(top, text="", font=("Segoe UI", 10, "bold"))
        self.header.pack(side="left")
        for cmd, label in [("1", "Я"), ("2", "Партии"), ("3", "Пресса"), ("4", "Журнал"),
                           ("5", "Справка"), ("6", "Управление"), ("7", "Город"), ("0", "Завершить неделю")]:
            ttk.Button(top, text=label, command=lambda c=cmd: self.on_command(c)).pack(side="right", padx=2)

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=6, pady=4)
        self.left = tk.Text(body, width=38, state="disabled", wrap="word", font=("Segoe UI", 9))
        self.center = tk.Text(body, wrap="word", font=("Segoe UI", 9))
        self.right = tk.Text(body, width=38, state="disabled", wrap="word", font=("Segoe UI", 9))
        self.left.pack(side="left", fill="y")
        self.right.pack(side="right", fill="y")
        self.center.pack(side="left", fill="both", expand=True)

        quick = ttk.Frame(self.root)
        quick.pack(fill="x", padx=6)
        for aid, title in (action_titles or [])[:14]:
            ttk.Button(quick, text=title, command=lambda a=aid: self.on_command("action:" + a)).pack(side="left", padx=1, pady=1)

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=6, pady=6)
        self.entry = ttk.Entry(bottom, font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, ipady=2)
        self.entry.bind("<Return>", lambda e: self._submit())
        self.entry.bind("<Up>", lambda e: self._history_step(-1))
        self.entry.bind("<Down>", lambda e: self._history_step(1))
        self._history: List[str] = []
        self._hist_pos = 0
        ttk.Button(bottom, text="▶", command=self._submit).pack(side="left", padx=4)

    def _history_step(self, step: int) -> str:
        if not self._history:
            return "break"
        self._hist_pos = max(0, min(len(self._history), self._hist_pos + step))
        self.entry.delete(0, "end")
        if self._hist_pos < len(self._history):
            self.entry.insert(0, self._history[self._hist_pos])
        return "break"

    def _submit(self) -> None:
        cmd = self.entry.get().strip()
        if cmd and (not self._history or self._history[-1] != cmd):
            self._history.append(cmd)
        self._hist_pos = len(self._history)
        self.entry.delete(0, "end")
        if cmd:
            self.on_command(cmd)

    def _close(self) -> None:
        self.on_close()

    def refresh(self, state: GameState, message: str) -> None:
        self.header.config(text=render_header(state))
        for widget, content in ((self.left, render_left(state)),
                                (self.right, render_right(state)),
                                (self.center, render_center(state, message))):
            widget.config(state="normal")
            widget.delete("1.0", "end")
            widget.insert("end", content)
            if widget is not self.center:
                widget.config(state="disabled")
        self.center.see("1.0")
        self.entry.focus_set()

    def open_modal(self, text: str) -> None:
        tk = self.tk
        ttk = self.ttk
        win = tk.Toplevel(self.root)
        win.title("Экран")
        win.geometry("720x560")
        win.transient(self.root)
        txt = tk.Text(win, wrap="word", font=("Segoe UI", 10))
        scr = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=scr.set)
        scr.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("end", text)
        txt.config(state="disabled")
        ttk.Button(win, text="Закрыть", command=win.destroy).pack(pady=4)
        win.bind("<Escape>", lambda e: win.destroy())
        win.focus_set()

    def open_review(self, review: List[Dict[str, Any]], on_done: Callable[[List[Dict[str, Any]]], None]) -> None:
        tk = self.tk
        ttk = self.ttk
        if not review:
            on_done([])
            return
        win = tk.Toplevel(self.root)
        win.title("Ревизия недели")
        win.geometry("820x640")
        win.transient(self.root)
        win.grab_set()
        txt = tk.Text(win, wrap="word", font=("Segoe UI", 9), height=14)
        txt.pack(fill="both", expand=True, padx=6, pady=4)
        txt.insert("end", render_review(review))
        txt.config(state="disabled")
        form = ttk.Frame(win)
        form.pack(fill="x", padx=6, pady=2)
        vars_map: Dict[int, Any] = {}
        entries_map: Dict[int, Any] = {}
        for item in review:
            idx = item.get("index", 0)
            row = ttk.Frame(form)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=f"[{idx}] {item.get('title','')}").pack(side="left", padx=4)
            var = tk.StringVar(value="yes")
            vars_map[idx] = var
            ttk.Radiobutton(row, text="похоже", variable=var, value="yes").pack(side="left")
            ttk.Radiobutton(row, text="не похоже", variable=var, value="no").pack(side="left", padx=4)
            ent = ttk.Entry(row, width=40)
            ent.pack(side="left", fill="x", expand=True)
            entries_map[idx] = ent

        def submit() -> None:
            verdicts = []
            for item in review:
                idx = item.get("index", 0)
                verdicts.append({"index": idx, "verdict": vars_map[idx].get(),
                                 "correction": entries_map[idx].get().strip()})
            win.destroy()
            on_done(verdicts)

        ttk.Button(win, text="Применить и завершить неделю", command=submit).pack(pady=6)

    def run(self) -> None:
        self.root.mainloop()
