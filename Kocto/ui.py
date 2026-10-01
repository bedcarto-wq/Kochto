from __future__ import annotations

import textwrap
from typing import Any, Callable, Dict, List, Optional, Tuple

import models
import systems
from models import ElectoralSystem, GameState, PrisonStatus, Role, WEEKLY_ACTION_LIMIT

# Оформление/палитра — презентационный слой UI, НЕ игровой контент (не словари/действия/баланс/тексты мира).
PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
           "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]

PRISON_LABEL = {
    PrisonStatus.FREE: "на свободе",
    PrisonStatus.DETAINED: "задержан",
    PrisonStatus.ARRESTED: "под арестом",
    PrisonStatus.ESCAPED: "в бегах",
    PrisonStatus.FUGITIVE: "в розыске",
    PrisonStatus.UNDER_INVESTIGATION: "под следствием",
    PrisonStatus.TRIAL: "суд",
    PrisonStatus.PRISON: "в тюрьме",
}


def wrap(text: str, width: int = 76) -> List[str]:
    return textwrap.wrap(text, width=width) or [""]


def _src_tag(item: Dict[str, Any], state: GameState) -> str:
    if getattr(state, "detail_level", "нормально") != "полно":
        return ""
    src = item.get("source", "gen")
    return f" [{src}]"


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _target_label(state: GameState, qa: Dict[str, Any]) -> str:
    intent = str(qa.get("intent", ""))
    target = str(qa.get("target", ""))
    if not target:
        return ""
    if intent in ("meet", "sponsor", "media", "party"):
        g = systems.get_group(state, target)
        if g:
            return g.name
        p = systems.get_party(state, target)
        if p:
            return p.name
    if intent == "attack":
        c = systems.get_candidate(state, target)
        if c:
            return c.name
    if intent == "bill":
        return target
    return target


def _action_title(action_id: str) -> str:
    a = systems.ACTIONS.get(action_id)
    return a.title if a else action_id


# ================= рендер главного экрана =================
def render_header(state: GameState) -> str:
    level_name = getattr(state.village, "display_name", state.village.name)
    parts = [
        f"Неделя {state.current_week}",
        f"Уровень: {level_name}",
        f"Деньги: {state.player.money}",
        f"Казна: {state.treasury}",
        f"Система: {state.electoral_system.value}",
        f"Роль: {state.player.role.value}",
        f"План: {len(state.week_actions)}/{WEEKLY_ACTION_LIMIT}",
    ]
    return "  |  ".join(parts)


def render_left(state: GameState) -> str:
    pl = state.player
    lines = ["── Я ──"]
    lines.append(f"Имя: {pl.name} ({pl.age})")
    lines.append(f"Роль: {pl.role.value}")
    party_name = ""
    if pl.party_id:
        p = systems.get_party(state, pl.party_id)
        party_name = p.name if p else pl.party_id
    lines.append(f"Партия: {party_name or '—'} ({pl.party_role or '—'})")
    lines.append(f"Деньги: {pl.money}")
    lines.append(f"Здоровье: {pl.health}  Стресс: {pl.stress}  Усталость: {pl.fatigue}")
    lines.append(f"Узнаваемость: {pl.awareness}  Доверие: {pl.trust}  Анти: {pl.anti_awareness}")
    lines.append(f"Улики: {pl.evidence}  Следствие: {pl.investigation}  Угроза: {pl.threat}")
    lines.append(f"Побег (подготовка): {pl.escape_prep}")
    lines.append(f"Статус: {PRISON_LABEL.get(pl.prison_status, pl.prison_status.value)}")
    if pl.legacy_tags:
        lines.append("Наследие: " + ", ".join(pl.legacy_tags[-5:]))
    return "\n".join(lines) + "\n"


def render_right(state: GameState) -> str:
    lines = ["── Фракции / власть ──"]
    info = systems.budget_info(state)
    lines.append(f"Казна: {info['treasury']}  Доход/нед: {info['income']}  Расход/нед: {info['expenses']}")
    lines.append(f"Мест в совете (игрок): {state.council_seats}")
    lines.append(f"Следующие выборы: нед. {state.next_election_week}  (прошло: {state.election_count})")
    lines.append("")
    lines.append("Партии:")
    for p in state.parties:
        share = systems.support_share(state, p.name, "party")
        lines.append(f"  · {p.name}: поп. {p.popularity}  доверие {p.trust_to_player}  места {p.seats}  поддержка {_pct(share)}")
    player_share = systems.support_share(state, state.player.name, "candidate")
    lines.append(f"  · Игрок ({state.player.name}): узнав. {state.player.awareness}  доверие {state.player.trust}  поддержка {_pct(player_share)}")
    lines.append("")
    lines.append("Места парламента:")
    for pid, seats in sorted(state.parliament_seats.items(), key=lambda kv: kv[1], reverse=True):
        nm = pid
        p = systems.get_party(state, pid)
        if p:
            nm = p.name
        elif pid == "player":
            nm = state.player.name
        lines.append(f"  {nm}: {seats}")
    return "\n".join(lines) + "\n"


def render_center(state: GameState, message: str) -> str:
    lines: List[str] = []
    if message:
        lines += [f">> {m}" for m in wrap(message, 76)]
        lines.append("")
    if state.week_actions:
        lines.append("── План недели (резолв в конце) ──")
        for qa in state.week_actions:
            title = _action_title(str(qa.get("action_id", "")))
            tgt = _target_label(state, qa)
            tag = " [отложено]" if qa.get("delayed") else ""
            line = f"  · {title}" + (f" → {tgt}" if tgt else "") + tag
            lines.append(line)
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
        prefix = f"  [№{no}] [{wk}] {pub} | тон {tone:+.2f}{_src_tag(item, state)}"
        lines.append(prefix)
        for w in wrap(head, 72):
            lines.append(f"    {w}")
    lines.append("")
    lines.append("0/пусто — завершить неделю · 1 Я · 2 Партии · 3 Пресса · 4 Журнал · 5 Справка · 6 Управление")
    return "\n".join(lines) + "\n"


def render_main(state: GameState, message: str) -> str:
    header = render_header(state)
    left = render_left(state)
    right = render_right(state)
    center = render_center(state, message)
    bar = "=" * 78
    return "\n".join([bar, header, bar, left, "─" * 39, right, "─" * 39, center, bar]) + "\n"


# ================= модальные экраны =================
def _modal_me(state: GameState) -> str:
    pl = state.player
    lines = ["═" * 78, "ЭКРАН: Я (навыки)", "═" * 78]
    skills = [("Харизма", pl.charisma), ("Убеждение", pl.persuasion), ("Организация", pl.organization),
              ("Медиа", pl.media), ("Администрирование", pl.administration), ("Скрытность", pl.stealth),
              ("Связи", pl.connections), ("Безопасность", pl.security)]
    for name, val in skills:
        lines.append(f"  {name:<18} {val:>3}")
    lines.append("")
    lines.append(render_left(state))
    return "\n".join(lines) + "\n"


def _modal_parties(state: GameState) -> str:
    lines = ["═" * 78, "ЭКРАН: ПАРТИИ", "═" * 78]
    lines.append(render_right(state))
    return "\n".join(lines) + "\n"


def _modal_press(state: GameState) -> str:
    lines = ["═" * 78, "ЭКРАН: ПРЕССА", "═" * 78]
    lines.append("Издания:")
    for pub in state.publications:
        lines.append(f"  · {pub.name}: тон {pub.tone:+.2f}  охват {pub.reach}")
    lines.append("")
    lines.append("Все вырезки (архив):")
    for item in list(state.clippings)[-15:]:
        head = item.get("headline", "")
        tone = float(item.get("tone", 0.0))
        pub = item.get("publication", "")
        wk = item.get("week", "?")
        no = item.get("archive_no", "?")
        lines.append(f"  [№{no}] [{wk}] {pub} | тон {tone:+.2f}{_src_tag(item, state)}")
        for w in wrap(head, 72):
            lines.append(f"    {w}")
        body = item.get("body", "")
        for w in wrap(body, 72):
            lines.append(f"      {w}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _modal_log(state: GameState) -> str:
    lines = ["═" * 78, "ЭКРАН: ЖУРНАЛ", "═" * 78]
    lines += state.event_log[-50:]
    return "\n".join(lines) + "\n"


def _modal_gov(state: GameState) -> str:
    info = systems.budget_info(state)
    lines = ["═" * 78, "ЭКРАН: УПРАВЛЕНИЕ", "═" * 78]
    lines.append(f"Казна: {info['treasury']}  Доход/нед: {info['income']}  Расход/нед: {info['expenses']}  Баланс: {info['net']:+}")
    lines.append("")
    lines.append("Законопроекты в процессе:")
    if not state.bills:
        lines.append("  (нет)")
    for b in state.bills:
        lines.append(f"  · {b.get('title','')} — стадия: {b.get('stage','?')}")
    lines.append("")
    lines.append("Принятые законы:")
    if not state.enacted_laws:
        lines.append("  (нет)")
    for l in state.enacted_laws[-15:]:
        lines.append(f"  · {l.get('title','')} (нед. {l.get('enacted_week','?')})")
    lines.append("")
    lines.append("Обещания:")
    if not state.promises:
        lines.append("  (нет)")
    for pr in state.promises:
        lines.append(f"  · [{pr.get('status','?')}] {pr.get('text','')} (до нед. {pr.get('deadline_week','?')}, прогресс {pr.get('progress',0)}%)")
    return "\n".join(lines) + "\n"


def _modal_help(state: GameState) -> str:
    lines = ["═" * 78, "СПРАВКА", "═" * 78]
    lines.append("Управление: 0/пусто — завершить неделю · 1 Я · 2 Партии · 3 Пресса · 4 Журнал · 5 Справка · 6 Управление")
    lines.append("Команды: выбор N · детализация кратко|нормально|полно · память очистить · преодолеть вето")
    lines.append("Свободный закон: «внеси закон <текст>» — после запроса впишешь тело закона строкой.")
    lines.append("")
    lines.append("Доступные действия (пиши своими словами, парсер распознаёт):")
    for a in systems.ACTIONS.values():
        lines.append(f"  · {a.title} — {a.description}")
    lines.append("═" * 78)
    return "\n".join(lines) + "\n"


def _modal_gameover(state: GameState) -> str:
    pl = state.player
    lines = ["═" * 78, "ИГРА ЗАВЕРШЕНА", "═" * 78]
    reason = state.game_over_reason or "неизвестно"
    lines.append(f"Причина: {reason}")
    lines.append(f"Недель прожито: {state.week}")
    lines.append(f"Выборов пройдено: {state.election_count}")
    lines.append(f"Итоговая роль: {pl.role.value}")
    lines.append(f"Наследие: {', '.join(pl.legacy_tags) if pl.legacy_tags else '—'}")
    lines.append("═" * 78)
    return "\n".join(lines) + "\n"


_MODAL_MAP: Dict[str, Callable[[GameState], str]] = {
    "me": _modal_me,
    "parties": _modal_parties,
    "press": _modal_press,
    "log": _modal_log,
    "gov": _modal_gov,
    "help": _modal_help,
    "gameover": _modal_gameover,
}


def render_modal(kind: str, state: GameState) -> str:
    fn = _MODAL_MAP.get(kind)
    if fn is None:
        return f"Неизвестный экран: {kind}"
    return fn(state)


# ================= ревизия конца недели =================
def render_review(review: List[Dict[str, Any]]) -> str:
    lines = ["═" * 78, "РЕВИЗИЯ НЕДЕЛИ — похоже ли то, что произошло?", "═" * 78]
    if not review:
        lines.append("(нет событий для ревизии)")
        return "\n".join(lines) + "\n"
    for item in review:
        idx = item.get("index", "?")
        title = item.get("title", "")
        tier = item.get("tier", "")
        lines.append("")
        lines.append(f"[{idx}] {title} — исход: {tier}")
        script = item.get("script", {}) or {}
        primary = script.get("primary", "")
        for w in wrap(primary, 74):
            lines.append(f"    {w}")
        for sec in script.get("secondary", []) or []:
            for w in wrap(str(sec), 74):
                lines.append(f"      · {w}")
        text = item.get("text") or {}
        if text:
            head = text.get("headline", "")
            lead = text.get("lead", "")
            body = text.get("body", "")
            lines.append("    — вырезка —")
            for w in wrap(head, 72):
                lines.append(f"      {w}")
            if lead:
                for w in wrap(lead, 72):
                    lines.append(f"      {w}")
            for w in wrap(body, 72):
                lines.append(f"      {w}")
        lines.append("    похоже? (да/нет)  ·  если нет — что не так (строкой)")
    lines.append("")
    lines.append("═" * 78)
    return "\n".join(lines) + "\n"


# ================= выбор трактовок / A/B =================
def render_choices(choices: List[Tuple[str, str]], state: GameState) -> str:
    lines = ["Выбери трактовку (введи: выбор N):"]
    for i, (aid, title) in enumerate(choices, 1):
        lines.append(f"  {i}) {title}  [{aid}]")
    return "\n".join(lines)


def render_ab_choices(ab_proposals: List[Dict[str, Any]], state: GameState) -> str:
    lines = ["Два распознавателя предложили варианты — выбери, кто точнее (введи: выбор N):"]
    counter = 1
    for pair in ab_proposals:
        parser_prop = (pair or {}).get("parser") or {}
        nn_prop = (pair or {}).get("nn") or {}
        p_txt = _prop_line(parser_prop)
        n_txt = _prop_line(nn_prop)
        lines.append(f"  {counter}) парсер: {p_txt}")
        counter += 1
        lines.append(f"  {counter}) нейросеть: {n_txt}")
        counter += 1
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
    tgt = f" → {target}" if target else ""
    return f"{aid} ({intent}){tgt}, увер. {conf_f:.2f}"


# ================= Tkinter-слой =================
def tk_available() -> bool:
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def ask_profile() -> Tuple[str, int]:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    holder = {"name": "Игрок", "age": 35, "done": False}

    win = tk.Toplevel(root)
    win.title("Новая кампания")
    win.geometry("320x160")
    win.transient(root)
    win.grab_set()

    tk.Label(win, text="Имя персонажа:").pack(anchor="w", padx=10, pady=(10, 0))
    name_var = tk.StringVar(value="Игрок")
    tk.Entry(win, textvariable=name_var, width=30).pack(anchor="w", padx=10)
    tk.Label(win, text="Возраст:").pack(anchor="w", padx=10, pady=(6, 0))
    age_var = tk.StringVar(value="35")
    tk.Entry(win, textvariable=age_var, width=10).pack(anchor="w", padx=10)

    def submit() -> None:
        holder["name"] = (name_var.get().strip() or "Игрок")
        try:
            holder["age"] = int(age_var.get().strip() or "35")
        except ValueError:
            holder["age"] = 35
        holder["done"] = True
        win.destroy()

    tk.Button(win, text="Начать", command=submit).pack(pady=10)
    win.protocol("WM_DELETE_WINDOW", submit)
    root.wait_window(win)
    root.destroy()
    return holder["name"], holder["age"]


class TkinterUI:
    def __init__(self, action_titles: List[Tuple[str, str]],
                 on_command: Callable[[str], None],
                 on_close: Callable[[], None]) -> None:
        import tkinter as tk
        self.tk = tk
        self.on_command = on_command
        self.on_close = on_close
        self.root = tk.Tk()
        self.root.title("Kochto — городская кампания")
        self.root.geometry("1100x720")
        self.root.configure(bg="#1e1e1e")
        self._build(action_titles)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self, action_titles: List[Tuple[str, str]]) -> None:
        tk = self.tk
        top = tk.Frame(self.root, bg="#1e1e1e")
        top.pack(side="top", fill="x", padx=8, pady=4)
        self.header = tk.Label(top, text="", anchor="w", bg="#1e1e1e", fg="#dcdcaa",
                               font=("Consolas", 10, "bold"))
        self.header.pack(side="left")

        menu = tk.Frame(self.root, bg="#1e1e1e")
        menu.pack(side="top", fill="x", padx=8)
        for label, cmd in [("Я", "1"), ("Партии", "2"), ("Пресса", "3"),
                           ("Журнал", "4"), ("Справка", "5"), ("Управление", "6"),
                           ("Завершить неделю", "0")]:
            tk.Button(menu, text=label, command=lambda c=cmd: self._send(c),
                      bg="#2d2d30", fg="#ffffff", activebackground="#3e3e42").pack(side="left", padx=2, pady=2)

        body = tk.Frame(self.root, bg="#1e1e1e")
        body.pack(side="top", fill="both", expand=True, padx=8, pady=4)
        self.text = tk.Text(body, bg="#1e1e1e", fg="#e0e0e0", wrap="word",
                            font=("Consolas", 10), insertbackground="#ffffff", relief="flat")
        scroll = tk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        bottom = tk.Frame(self.root, bg="#1e1e1e")
        bottom.pack(side="bottom", fill="x", padx=8, pady=6)
        self.entry = tk.Entry(bottom, bg="#2d2d30", fg="#ffffff", insertbackground="#ffffff",
                              font=("Consolas", 11), relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.entry.bind("<Return>", lambda e: self._submit())
        tk.Button(bottom, text="▶", command=self._submit, bg="#0e639c", fg="#ffffff").pack(side="left", padx=4)

        # быстрые действия (названия из данных, не вшиты)
        quick = tk.Frame(self.root, bg="#1e1e1e")
        quick.pack(side="bottom", fill="x", padx=8)
        for aid, title in action_titles[:12]:
            tk.Button(quick, text=title, command=lambda a=aid: self._send("action:" + a),
                      bg="#252526", fg="#cccccc", activebackground="#3e3e42",
                      font=("Consolas", 8)).pack(side="left", padx=1, pady=1)

    def _send(self, cmd: str) -> None:
        self.on_command(cmd)

    def _submit(self) -> None:
        cmd = self.entry.get().strip()
        self.entry.delete(0, "end")
        if cmd:
            self.on_command(cmd)

    def _close(self) -> None:
        self.on_close()

    def refresh(self, state: GameState, message: str) -> None:
        self.header.config(text=render_header(state))
        self.text.delete("1.0", "end")
        self.text.insert("end", render_left(state))
        self.text.insert("end", "─" * 39 + "\n")
        self.text.insert("end", render_right(state))
        self.text.insert("end", "─" * 39 + "\n")
        self.text.insert("end", render_center(state, message))
        self.text.see("end")

    def open_modal(self, text: str) -> None:
        win = self.tk.Toplevel(self.root)
        win.title("Экран")
        win.geometry("720x560")
        win.transient(self.root)
        txt = self.tk.Text(win, bg="#1e1e1e", fg="#e0e0e0", wrap="word", font=("Consolas", 10))
        scr = self.tk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=scr.set)
        scr.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("end", text)
        txt.config(state="disabled")
        self.tk.Button(win, text="Закрыть", command=win.destroy).pack(pady=4)

    def open_review(self, review: List[Dict[str, Any]], on_done: Callable[[List[Dict[str, Any]]], None]) -> None:
        win = self.tk.Toplevel(self.root)
        win.title("Ревизия недели")
        win.geometry("820x640")
        win.transient(self.root)
        win.grab_set()
        canvas_frame = self.tk.Frame(win)
        canvas_frame.pack(fill="both", expand=True)
        canvas = self.tk.Canvas(canvas_frame, bg="#1e1e1e", highlightthickness=0)
        vsb = self.tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        inner = self.tk.Frame(canvas, bg="#1e1e1e")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        vars_map: Dict[int, Any] = {}
        entries_map: Dict[int, Any] = {}
        for item in review:
            idx = item.get("index", 0)
            frame = self.tk.Frame(inner, bg="#252526", bd=1, relief="groove")
            frame.pack(fill="x", padx=6, pady=4)
            title = item.get("title", "")
            tier = item.get("tier", "")
            script = item.get("script", {}) or {}
            text = item.get("text") or {}
            body_lines = [f"[{idx}] {title} — {tier}", str(script.get("primary", ""))]
            for sec in script.get("secondary", []) or []:
                body_lines.append("· " + str(sec))
            if text:
                body_lines.append("— вырезка —")
                body_lines.append(str(text.get("headline", "")))
                if text.get("lead"):
                    body_lines.append(str(text.get("lead", "")))
                body_lines.append(str(text.get("body", "")))
            lbl = self.tk.Label(frame, text="\n".join(body_lines), justify="left",
                                anchor="w", bg="#252526", fg="#e0e0e0", font=("Consolas", 9))
            lbl.pack(side="top", fill="x", padx=6, pady=4)
            row = self.tk.Frame(frame, bg="#252526")
            row.pack(side="top", fill="x", padx=6, pady=2)
            var = self.tk.StringVar(value="yes")
            vars_map[idx] = var
            self.tk.Radiobutton(row, text="похоже", variable=var, value="yes",
                                bg="#252526", fg="#9cdc9c", selectcolor="#1e1e1e").pack(side="left")
            self.tk.Radiobutton(row, text="не похоже", variable=var, value="no",
                                bg="#252526", fg="#f48771", selectcolor="#1e1e1e").pack(side="left", padx=8)
            ent = self.tk.Entry(row, bg="#2d2d30", fg="#ffffff", insertbackground="#ffffff", width=40)
            ent.pack(side="left", fill="x", expand=True)
            entries_map[idx] = ent

        def submit() -> None:
            verdicts = []
            for item in review:
                idx = item.get("index", 0)
                verdicts.append({
                    "index": idx,
                    "verdict": vars_map[idx].get(),
                    "correction": entries_map[idx].get().strip(),
                })
            win.destroy()
            on_done(verdicts)

        self.tk.Button(win, text="Применить и завершить неделю", command=submit,
                       bg="#0e639c", fg="#ffffff").pack(pady=6)
        if not review:
            win.destroy()
            on_done([])

    def run(self) -> None:
        self.root.mainloop()