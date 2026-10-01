from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import language
import models
import systems
import ui
from models import DataError, DETAIL_ALIASES, ParseStatus, WEEKLY_ACTION_LIMIT

# ================= пути / константы движка =================
DATA_DIR: Path = models.DATA_DIR
SAVE_DIR: Path = models.SAVE_DIR
SAVE_FILE: Path = SAVE_DIR / "save.json"
MEMORY_FILE: Path = SAVE_DIR / "parser_memory.json"
ACTIVE_SCENARIO = "city.json"   # Q-B2=α: играбелен только город; регион/федерация — скелеты в сейве

DEFAULT_SEED = 20240101
SCHEMA_TAG = "kochto.proto.1"


# ================= служебные хелперы (контракт UI, не игровой контент) =================
def _flatten_ab(ab_proposals: List[Dict[str, Any]]) -> List[Tuple[int, str, Dict[str, Any]]]:
    """Разворачивает пары {parser,nn} в плоский список в том же порядке, что печатает
    ui.render_ab_choices (1=парсер пары0, 2=нейросеть пары0, 3=парсер пары1, ...)."""
    flat: List[Tuple[int, str, Dict[str, Any]]] = []
    for i, pair in enumerate(ab_proposals or []):
        p = (pair or {}).get("parser") or {}
        n = (pair or {}).get("nn") or {}
        flat.append((i, "parser", p))
        flat.append((i, "nn", n))
    return flat


def _nn_recognizer_available() -> bool:
    try:
        import nn_recognizer  # noqa: F401
        return bool(nn_recognizer.available())
    except Exception:
        return False


def _nn_law_available() -> bool:
    try:
        import nn_recognizer  # noqa: F401
        return callable(getattr(nn_recognizer, "type_law", None))
    except Exception:
        return False


def _clear_pending(state: models.GameState) -> None:
    ctx = state.parser_context
    ctx["pending_ab_flat"] = []
    ctx["pending_ab_raw"] = []
    ctx["pending_options"] = []
    ctx["pending_law"] = None
    ctx["pending_law_body"] = ""


# ================= директории / резервные копии =================
def ensure_dirs() -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)


def _backup_corrupt(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    bak = path.with_suffix(path.suffix + ".bak")
    try:
        path.replace(bak)
        return bak
    except Exception:
        return None


# ================= сейв / лоад =================
def save_game(state: models.GameState, rng: random.Random) -> None:
    ensure_dirs()
    state.rng_state = systems.rng_state_to_json(rng)
    payload = models.game_to_dict(state)
    payload["_schema"] = SCHEMA_TAG
    models.save_json(SAVE_FILE, payload)


PLAYTEST = {"on": False}


def playtest_on() -> bool:
    return bool(PLAYTEST["on"])


def _migrate_save(state: models.GameState) -> Optional[str]:
    """Старые сейвы: выборы когда-то завершали игру. По канону game over — только смерть."""
    if state.is_game_over and state.game_over_reason != "death":
        old = state.game_over_reason
        state.is_game_over = False
        state.game_over_reason = ""
        if state.next_election_week < state.week:
            state.next_election_week = state.week
        return "Сейв из старой версии: игра была завершена («" + str(old) + "»), кампания продолжена."
    return None


def load_game() -> Tuple[Optional[models.GameState], Optional[random.Random], Optional[str]]:
    if not SAVE_FILE.exists():
        return None, None, None
    try:
        raw = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("сейв не объект JSON")
        state = models.game_from_dict(raw)
        note = _migrate_save(state)
        if state.is_game_over:
            # смерть — конец этой жизни; сейв уходит в архив, запускается новая кампания
            arch = SAVE_DIR / ("save_dead_week" + str(state.week) + ".json")
            try:
                SAVE_FILE.replace(arch)
            except Exception:
                pass
            return None, None, "Прошлая кампания окончена (" + str(state.game_over_reason) + "). Сейв в архиве: " + arch.name + "."
        rng = systems.rng_from_state(state.rng_state, state.seed)
        return state, rng, note
    except Exception as exc:
        bak = _backup_corrupt(SAVE_FILE)
        note = ""
        if bak is not None:
            note = " Повреждённый сейв перемещён в " + str(bak.name) + "."
        return None, None, "Сохранение повреждено (" + str(exc) + ")." + note


def load_memory() -> Dict[str, Any]:
    if not MEMORY_FILE.exists():
        return {}
    try:
        raw = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        _backup_corrupt(MEMORY_FILE)
        return {}


def save_memory(memory: Dict[str, Any]) -> None:
    ensure_dirs()
    models.save_json(MEMORY_FILE, memory)


def add_memory(memory: Dict[str, Any], raw_text: str, action_id: str, intent: str) -> None:
    dicts = systems.DATA.dictionaries if systems.DATA else {}
    norm = language.normalize(raw_text, dicts)
    if not norm:
        return
    memory[norm] = {"id": action_id, "intent": intent}
    while len(memory) > 500:
        memory.pop(next(iter(memory)))


# ================= новая игра =================
def new_game(data: models.GameData, seed: int, name: str, age: int) -> Tuple[models.GameState, random.Random]:
    state = models.build_state(data, seed)
    state.player.name = name or "Игрок"
    state.player.age = int(age) if int(age) > 0 else 35
    rng = random.Random(seed)
    systems.draw_next_week_seed(state)
    return state, rng


# ================= постановка действия =================
def _enqueue(state: models.GameState, action_id: str, target: str, intent: str, delayed: bool,
             issue: str = "", meta: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    action = systems.ACTIONS.get(action_id)
    if not action:
        return False, "Действие не найдено: " + str(action_id)
    return systems.enqueue_action(state, action, target, intent, delayed, issue, meta)


def _examples_hint() -> str:
    data = systems.DATA
    ex = ((getattr(data, "world", None) or {}).get("ui") or {}).get("examples") or [] if data else []
    if not ex:
        return ""
    return " Например: «" + "», «".join(str(x) for x in ex[:3]) + "». Все примеры — 5 (справка)."


# ================= отзывы плейтеста =================
FEEDBACK_FILE: Path = SAVE_DIR / "feedback.txt"
SESSION: Dict[str, Any] = {"phrases": 0, "free": 0, "not_understood": [], "weeks": 0, "errors": []}


def _feedback(state: models.GameState, text: str) -> str:
    ensure_dirs()
    line = "[нед. " + str(state.week) + "] " + text.strip() + "\n"
    with open(FEEDBACK_FILE, "a", encoding="utf-8") as fh:
        fh.write(line)
    return "Спасибо! Отзыв записан в " + str(FEEDBACK_FILE) + "."


def write_session_report(state: Optional[models.GameState]) -> Optional[Path]:
    """Итог сессии для автора: что не понял парсер, сколько недель, ошибки. Без личных данных."""
    try:
        ensure_dirs()
        path = SAVE_DIR / "playtest_report.txt"
        lines = ["=== Кочто: отчёт сессии ===",
                 "Неделя: " + str(state.week if state else "?") + ", недель за сессию: " + str(SESSION["weeks"]),
                 "Фраз введено: " + str(SESSION["phrases"]) + ", из них «своих действий»: " + str(SESSION["free"]),
                 "Не понял (" + str(len(SESSION["not_understood"])) + "):"]
        lines += ["  · " + t for t in SESSION["not_understood"][-60:]]
        if SESSION.get("free_phrases"):
            lines.append("Стали «своим действием» (проверить, правильно ли поняты):")
            lines += ["  · " + t for t in SESSION["free_phrases"][-60:]]
        if SESSION["errors"]:
            lines.append("Внутренние ошибки:")
            lines += ["  · " + t for t in SESSION["errors"][-30:]]
        if state is not None:
            pl = state.player
            lines.append("Итог: роль " + str(pl.role.value) + ", узнав. " + str(pl.awareness) + ", доверие " +
                         str(pl.trust) + ", деньги " + str(pl.money) + ", выборов " + str(state.election_count))
        if FEEDBACK_FILE.exists():
            lines.append("Отзывы:")
            lines += ["  " + t for t in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines()[-60:]]
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n\n")
        return path
    except Exception:
        return None


# ================= свободные законы =================
def _do_law(state: models.GameState, rng: random.Random, body_text: str,
            memory: Dict[str, Any], raw_cmd: str) -> Dict[str, Any]:
    body_text = (body_text or "").strip()
    if not body_text:
        return {"message": "Формат: внеси закон <текст>. Тело закона пустое.", "modal": None, "review": None}
    data = systems.DATA
    if data is None:
        return {"message": "Данные не загружены.", "modal": None, "review": None}
    try:
        parser_sk = language.type_law_text(body_text, state, data)
    except DataError as exc:
        return {"message": "Ошибка типизации закона: " + str(exc), "modal": None, "review": None}
    chosen_sk = parser_sk
    # A/B для законов (Q-D): подключаем lazily, игра работает без nn_recognizer
    if state.ab_mode and _nn_law_available():
        try:
            import nn_recognizer
            nn_sk = nn_recognizer.type_law(body_text, state, data)
            if nn_sk:
                pair = {"parser": {"id": "law_custom", "target": "", "intent": "law_custom",
                                   "confidence": 1.0, "skeleton": parser_sk},
                        "nn": {"id": "law_custom", "target": "", "intent": "law_custom",
                               "confidence": 1.0, "skeleton": nn_sk}}
                state.parser_context["pending_law"] = pair
                state.parser_context["pending_law_body"] = body_text
                msg = "Два распознавателя типизировали закон — выбери (выбор 1 = парсер, выбор 2 = нейросеть)."
                return {"message": msg, "modal": None, "review": None}
        except Exception:
            chosen_sk = parser_sk
    ok, msg = systems.create_custom_law(state, body_text, chosen_sk)
    if ok:
        save_game(state, rng)
    return {"message": msg, "modal": None, "review": None}


def _resolve_pending_law(state: models.GameState, rng: random.Random, idx: int,
                         memory: Dict[str, Any]) -> Dict[str, Any]:
    pair = state.parser_context.get("pending_law")
    body = state.parser_context.get("pending_law_body", "")
    state.parser_context["pending_law"] = None
    state.parser_context["pending_law_body"] = ""
    if not pair:
        return {"message": "Нет ожидающей типизации закона.", "modal": None, "review": None}
    if idx == 1:
        sk = pair.get("parser", {})
        src = "parser"
    elif idx == 2:
        sk = pair.get("nn", {})
        src = "nn"
    else:
        return {"message": "Нет такого варианта.", "modal": None, "review": None}
    skeleton = (sk or {}).get("skeleton") or {}
    systems.log_ab_judgment({"week": state.week, "seed": state.seed,
                             "phrase": "law:" + str(body)[:60], "chosen": src, "proposal": sk})
    ok, msg = systems.create_custom_law(state, body, skeleton)
    if ok:
        save_game(state, rng)
    return {"message": msg, "modal": None, "review": None}


# ================= главный обработчик команды =================
def handle_command(state: models.GameState, rng: random.Random, cmd: str,
                   memory: Dict[str, Any]) -> Dict[str, Any]:
    cmd = (cmd or "").strip()
    data = systems.DATA
    dicts = data.dictionaries if data else {}

    # завершение недели
    if cmd == "" or cmd == "0":
        if state.is_game_over:
            return {"message": "Игра завершена.", "modal": "gameover", "review": None}
        review = systems.begin_week_end(state)
        return {"message": "", "modal": None, "review": review}

    if state.is_game_over:
        return {"message": "Игра завершена. Нажми 0/Enter для экрана итогов.", "modal": "gameover", "review": None}

    norm = language.normalize(cmd, dicts)

    # модалки
    if norm in ("1", "я", "me"):
        return {"message": "", "modal": "me", "review": None}
    if norm in ("2", "партии", "parties"):
        return {"message": "", "modal": "parties", "review": None}
    if norm in ("3", "пресса", "press"):
        return {"message": "", "modal": "press", "review": None}
    if norm in ("4", "журнал", "log"):
        return {"message": "", "modal": "log", "review": None}
    if norm in ("5", "справка", "help"):
        return {"message": "", "modal": "help", "review": None}
    if norm in ("6", "управление", "gov"):
        return {"message": "", "modal": "gov", "review": None}
    if norm in ("7", "город", "соперники", "world"):
        return {"message": "", "modal": "world", "review": None}

    # отзыв автору (плейтест)
    if cmd.lower().startswith("отзыв"):
        body = cmd[len("отзыв"):].strip(" :—-")
        if not body:
            return {"message": "Формат: отзыв <что понравилось/сломалось>.", "modal": None, "review": None}
        return {"message": _feedback(state, body), "modal": None, "review": None}

    # отмена действия из плана
    _parts = norm.split()
    if _parts and _parts[0] in ("отменить", "отмена") and (len(_parts) == 1 or (len(_parts) == 2 and _parts[1].isdigit())):
        idx = int(_parts[1]) if len(_parts) == 2 else len(state.week_actions)
        message = systems.cancel_action(state, idx)
        save_game(state, rng)
        return {"message": message, "modal": None, "review": None}

    # детализация
    if norm.startswith("детализация"):
        parts = cmd.split()
        lvl_raw = parts[-1] if len(parts) > 1 else ""
        level = DETAIL_ALIASES.get(lvl_raw.lower(), "")
        if not level:
            return {"message": "Формат: детализация кратко|нормально|полно.", "modal": None, "review": None}
        state.detail_level = level
        save_game(state, rng)
        return {"message": "Детализация отчётов: " + level + ".", "modal": None, "review": None}

    # преодолеть вето
    if norm == "преодолеть вето":
        message = systems.override_veto(state)
        save_game(state, rng)
        return {"message": message, "modal": None, "review": None}

    # забыть обещание
    if norm in ("забыть обещание", "скрыть обещание"):
        frng = systems.get_week_rng(state, 7)
        message = systems.forget_promise(state, frng)
        save_game(state, rng)
        return {"message": message, "modal": None, "review": None}

    # память парсера
    if norm == "память очистить":
        memory.clear()
        save_memory(memory)
        return {"message": "Память парсера очищена.", "modal": None, "review": None}

    # свободный закон (прямой путь)
    low = cmd.lower()
    if low.startswith("внеси закон ") or low.startswith("закон "):
        cut = "внеси закон " if low.startswith("внеси закон ") else "закон "
        body_text = cmd[len(cut):]
        return _do_law(state, rng, body_text, memory, cmd)

    # принудительный НС-вызов
    force = False
    text_for_parse = cmd
    if cmd.startswith("!"):
        force = True
        text_for_parse = cmd[1:].strip()
    elif low.startswith("нейросеть "):
        force = True
        text_for_parse = cmd[len("нейросеть "):].strip()

    # выбор трактовки / A/B / закона
    if norm.startswith("выбор"):
        try:
            idx = int(norm.split()[-1])
        except (ValueError, IndexError):
            return {"message": "Формат: выбор N.", "modal": None, "review": None}
        return _handle_choice(state, rng, idx, memory)

    # кнопка действия
    if cmd.startswith("action:"):
        action_id = cmd[len("action:"):]
        action = systems.ACTIONS.get(action_id)
        if not action:
            return {"message": "Действие не найдено.", "modal": None, "review": None}
        intent = action.intent
        ok, msg = _enqueue(state, action_id, "", intent, False)
        if ok:
            save_game(state, rng)
        return {"message": msg, "modal": None, "review": None}

    # обычная фраза -> парсер
    SESSION["phrases"] += 1
    if data is None:
        return {"message": "Данные не загружены.", "modal": None, "review": None}

    saved_ab = state.ab_mode
    if force:
        state.ab_mode = True
    try:
        parse_result = language.parse_text(text_for_parse, state, memory, data)
    except DataError as exc:
        state.ab_mode = saved_ab
        return {"message": "Ошибка парсера (данные): " + str(exc), "modal": None, "review": None}
    finally:
        state.ab_mode = saved_ab
    language.update_context(state, text_for_parse, parse_result)
    state.parser_context["last_phrase"] = text_for_parse

    status = parse_result.get("status")

    if status == ParseStatus.CANCELLED:
        aggressive = bool(parse_result.get("aggressive"))
        if aggressive:
            message = parse_result.get("message", "Действие отменено.")
        else:
            message = systems.apply_refusal(state)
        save_game(state, rng)
        return {"message": message, "modal": None, "review": None}

    if status in (ParseStatus.NEEDS_CHOICE, ParseStatus.NEEDS_REFORMULATION,
                  ParseStatus.TOO_MANY_ACTIONS, ParseStatus.UNKNOWN):
        message = parse_result.get("message", "Не распознано.")
        opts = parse_result.get("options") or []
        if status in (ParseStatus.NEEDS_REFORMULATION, ParseStatus.UNKNOWN):
            SESSION["not_understood"].append(text_for_parse[:120])
            message += _examples_hint()
        if opts:
            state.parser_context["pending_options"] = opts
        return {"message": message, "modal": None, "review": None}

    # PARSED
    ab_proposals = parse_result.get("ab_proposals") or []
    actions = parse_result.get("actions") or []

    if ab_proposals:
        flat = _flatten_ab(ab_proposals)
        state.parser_context["pending_ab_flat"] = flat
        state.parser_context["pending_ab_raw"] = ab_proposals
        msg = ui.render_ab_choices(ab_proposals, state)
        return {"message": msg, "modal": None, "review": None}

    if not actions:
        return {"message": "Не распознано.", "modal": None, "review": None}

    messages: List[str] = []
    all_ok = True
    last_action_id = ""
    last_intent = ""
    for a in actions:
        aid = str(a.get("id", ""))
        tgt = str(a.get("target", ""))
        intent = str(a.get("intent", ""))
        delayed = bool(a.get("delayed", False))
        meta = {"tags": a.get("tags") or [], "stance": a.get("stance", ""), "offer": a.get("offer", ""),
                "raw": a.get("raw", "") or text_for_parse}
        if aid == "free_action":
            SESSION["free"] += 1
            SESSION.setdefault("free_phrases", []).append(text_for_parse[:120])
        ok, msg = _enqueue(state, aid, tgt, intent, delayed, str(a.get("issue", "") or ""), meta)
        messages.append(msg)
        if not ok:
            all_ok = False
        else:
            last_action_id = aid
            last_intent = intent

    if all_ok and len(actions) == 1 and last_action_id:
        add_memory(memory, text_for_parse, last_action_id, last_intent)
        try:
            feats = language.extract_features(text_for_parse, state, data)
            language.remember_construction(feats, last_intent, last_action_id, text_for_parse)
        except Exception:
            pass
        save_game(state, rng)
    elif all_ok:
        save_game(state, rng)

    return {"message": "".join(messages), "modal": None, "review": None}


def _handle_choice(state: models.GameState, rng: random.Random, idx: int,
                   memory: Dict[str, Any]) -> Dict[str, Any]:
    # 1) ожидающая типизация закона
    if state.parser_context.get("pending_law"):
        return _resolve_pending_law(state, rng, idx, memory)

    # 2) A/B распознавание
    flat = state.parser_context.get("pending_ab_flat") or []
    if flat:
        if not (1 <= idx <= len(flat)):
            return {"message": "Нет такого варианта.", "modal": None, "review": None}
        _pair_idx, source, prop = flat[idx - 1]
        state.parser_context["pending_ab_flat"] = []
        state.parser_context["pending_ab_raw"] = []
        if not prop or not prop.get("id"):
            return {"message": "Этот источник не предложил действия.", "modal": None, "review": None}
        systems.log_ab_judgment({"week": state.week, "seed": state.seed,
                                 "phrase": str(state.parser_context.get("last_phrase", "")),
                                 "chosen": source, "proposal": prop})
        ok, msg = _enqueue(state, str(prop.get("id", "")), str(prop.get("target", "")),
                           str(prop.get("intent", "")), bool(prop.get("delayed", False)))
        if ok:
            save_game(state, rng)
        return {"message": msg, "modal": None, "review": None}

    # 3) трактовки NeedsChoice
    options = state.parser_context.get("pending_options") or []
    if options:
        if not (1 <= idx <= len(options)):
            return {"message": "Нет такой трактовки.", "modal": None, "review": None}
        opt = options[idx - 1]
        state.parser_context["pending_options"] = []
        aid = str(opt.get("action_id", ""))
        intent = str(opt.get("intent", ""))
        ok, msg = _enqueue(state, aid, "", intent, False)
        if ok:
            save_game(state, rng)
        return {"message": msg, "modal": None, "review": None}

    return {"message": "Нет ожидающего выбора.", "modal": None, "review": None}


# ================= консольная ревизия =================
def _console_review(state: models.GameState, review: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not review:
        return []
    print(ui.render_review(review, ask=False))
    if not playtest_on():
        # обычная игра: итоги недели только показываются, игрока не просят оценивать
        try:
            input("Enter — продолжить.")
        except (EOFError, KeyboardInterrupt):
            pass
        return []
    verdicts: List[Dict[str, Any]] = []
    for item in review:
        idx = item.get("index", 0)
        while True:
            try:
                ans = input("Похоже? (да/нет) [по умолчанию да]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "да"
            if ans in ("", "да", "д", "yes", "y"):
                verdict = "yes"
                correction = ""
                break
            if ans in ("нет", "н", "no", "n"):
                verdict = "no"
                try:
                    correction = input("Что не так (строкой, Enter=пусто): ").strip()
                except (EOFError, KeyboardInterrupt):
                    correction = ""
                break
            print("Введи да или нет.")
        verdicts.append({"index": idx, "verdict": verdict, "correction": correction})
    return verdicts


# ================= циклы =================
def console_loop(state: models.GameState, rng: random.Random, memory: Dict[str, Any]) -> None:
    message = "Консольный режим. Enter — завершить неделю."
    while True:
        print("\n" * 2)
        print(ui.render_main(state, message))
        try:
            cmd = input("> ")
        except (EOFError, KeyboardInterrupt):
            save_game(state, rng)
            break
        try:
            result = handle_command(state, rng, cmd, memory)
        except Exception as exc:
            SESSION["errors"].append(repr(exc)[:200] + " на: " + cmd[:80])
            result = {"message": "Внутренняя ошибка: " + str(exc), "modal": None, "review": None}
        if result.get("review") is not None:
            review = result["review"]
            if review and playtest_on():
                verdicts = _console_review(state, review)
            else:
                verdicts = []
                if review:
                    print(ui.render_review(review, ask=False))
            before = systems.snapshot(state)
            systems.finish_week(state, verdicts)
            SESSION["weeks"] += 1
            _clear_pending(state)
            save_game(state, rng)
            message = "Неделя завершена. " + systems.week_summary(before, state)
            if state.is_game_over:
                print(ui.render_modal("gameover", state))
                break
            continue
        message = result.get("message", "")
        modal = result.get("modal")
        if modal:
            print(ui.render_modal(modal, state))
            if modal == "gameover":
                save_game(state, rng)
                break
            try:
                input("Enter — закрыть.")
            except (EOFError, KeyboardInterrupt):
                pass
            message = ""


def tk_loop(state: models.GameState, rng: random.Random, memory: Dict[str, Any]) -> None:
    action_titles = [(a.id, a.title) for a in systems.ACTIONS.values()]
    holder: Dict[str, Any] = {"tui": None}

    def on_command(cmd: str) -> None:
        try:
            result = handle_command(state, rng, cmd, memory)
        except Exception as exc:
            SESSION["errors"].append(repr(exc)[:200] + " на: " + cmd[:80])
            result = {"message": "Внутренняя ошибка: " + str(exc) + ". Окно обновлено.",
                      "modal": None, "review": None}

        if result.get("review") is not None:
            review = result["review"]

            before = systems.snapshot(state)

            def on_done(verdicts: List[Dict[str, Any]]) -> None:
                systems.finish_week(state, verdicts)
                SESSION["weeks"] += 1
                _clear_pending(state)
                save_game(state, rng)
                if state.is_game_over:
                    holder["tui"].open_modal(ui.render_modal("gameover", state))
                holder["tui"].refresh(state, "Неделя завершена. " + systems.week_summary(before, state))

            if review and playtest_on():
                holder["tui"].open_review(review, on_done)
            else:
                on_done([])
                if review:
                    holder["tui"].open_modal(ui.render_review(review, ask=False))
            return

        modal = result.get("modal")
        if modal:
            holder["tui"].open_modal(ui.render_modal(modal, state))
            if modal == "gameover":
                save_game(state, rng)
                holder["tui"].refresh(state, "Кампания окончена. Закрой окно — при следующем запуске начнётся новая.")
                return
        holder["tui"].refresh(state, result.get("message", ""))

    def on_close() -> None:
        save_game(state, rng)
        write_session_report(state)
        holder["tui"].root.destroy()

    tui = ui.TkinterUI(action_titles, on_command, on_close)
    holder["tui"] = tui
    tui.refresh(state, "Десктопный режим запущен. Enter/кнопка — завершить неделю.")
    tui.run()


# ================= самотест / реплей =================
def _selftest(data: models.GameData) -> int:
    print("SELFTEST: валидация данных пройдена (load_data без DataError).")
    systems.init_data(data, models.USER_DATA_DIR)
    ui.set_examples(((data.world or {}).get("ui") or {}).get("examples") or [])
    nn_analyzer_set(data)
    tmp_state = models.build_state(data, DEFAULT_SEED)
    violations = systems.selftest_composer(tmp_state, DEFAULT_SEED, n=120)
    print("SELFTEST композера: нарушений " + str(len(violations)) + " из 120 генераций.")
    for i, probs, head in violations[:10]:
        print("  #" + str(i) + ": " + str(probs) + " | " + str(head))
    return 0 if not violations else 1


def _replay() -> int:
    # Структурная проверка записей анализатора. Полный побитовый реплей скриптов до валидации
    # подключается вместе со снапшот-механикой при уходе от детерминизма (после рецензий).
    path = models.user_data_path(models.NN_EVAL_ANALYZER)
    records = models.read_jsonl(path)
    bad = 0
    for r in records:
        if "script" not in r or "week_seed" not in r:
            bad += 1
    print("REPLAY (структурный): записей " + str(len(records)) + ", без week_seed/script: " + str(bad) + ".")
    return 0 if bad == 0 else 1


# ================= nn_analyzer.set_data (закрытие долга серии) =================
def nn_analyzer_set(data: models.GameData) -> None:
    """НС-анализатор читает веса из data.nn['weights']['analyzer'], но его контракт
    analyze_action(state, action, tier, rng) не несёт GameData. Передаём ссылку один раз
    при старте. nn_recognizer/nn_writer читают JSON сами, set_data им не нужен."""
    try:
        import nn_analyzer
        if callable(getattr(nn_analyzer, "set_data", None)):
            nn_analyzer.set_data(data)
    except Exception:
        pass  # НС-анализатор опционален; при отсутствии systems откатится на fallback


# ================= точка входа =================
def _ask_seed_console() -> int:
    if sys.stdin is None or not sys.stdin.isatty():
        return DEFAULT_SEED
    try:
        txt = input("Сид новой игры (пусто = " + str(DEFAULT_SEED) + "): ").strip()
    except (EOFError, KeyboardInterrupt, RuntimeError):
        txt = ""
    if not txt:
        return DEFAULT_SEED
    try:
        return int(txt)
    except ValueError:
        return DEFAULT_SEED


def _ask_profile_console() -> Tuple[str, int]:
    try:
        name = input("Имя персонажа (пусто = Игрок): ").strip()
    except (EOFError, KeyboardInterrupt):
        name = ""
    try:
        age_txt = input("Возраст (пусто = 35): ").strip()
    except (EOFError, KeyboardInterrupt):
        age_txt = ""
    try:
        age = int(age_txt) if age_txt else 35
    except ValueError:
        age = 35
    return (name or "Игрок"), age


def _print_paths() -> None:
    print("Пути: DATA=" + str(models.DATA_DIR))
    print("Пути: USER_DATA (eval/рантайм)=" + str(models.USER_DATA_DIR))
    print("Пути: SAVES=" + str(models.SAVE_DIR))
    if models.frozen_build():
        print("Режим: сборка (PyInstaller) — пользовательские данные отдельно от файлов игры.")
    else:
        print("Режим: разработка — пользовательские данные рядом с кодом.")


def main() -> int:
    args = sys.argv[1:]
    flag_set = set(a for a in args if a.startswith("--"))

    if "--debug-parser" in flag_set:
        systems.set_debug_parser(True)
        print("ВНИМАНИЕ: debug-логи парсера ставят флаг; запись в parser_debug.jsonl подключится "
              "после переиздания language.py (зафиксированный долг).")

    try:
        data, warnings = models.load_data(DATA_DIR, ACTIVE_SCENARIO)
    except DataError as exc:
        print("ОШИБКА ДАННЫХ: " + str(exc))
        print("Игра не запускается без обязательных JSON. Проверь папку data/.")
        _print_paths()
        return 2

    for w in warnings:
        print("ПРЕДУПРЕЖДЕНИЕ ДАННЫХ: " + w)

    rt_warnings = models.ensure_runtime_files()
    for w in rt_warnings:
        print("ПРЕДУПРЕЖДЕНИЕ РАНТАЙМ: " + w)

    systems.init_data(data, models.USER_DATA_DIR)
    ui.set_examples(((data.world or {}).get("ui") or {}).get("examples") or [])
    nn_analyzer_set(data)
    PLAYTEST["on"] = bool(data.nn.get("playtest_mode", False)) or ("--playtest" in flag_set)
    language.init_constructions()

    if "--selftest" in flag_set:
        return _selftest(data)
    if "--replay" in flag_set:
        return _replay()

    state, rng, note = load_game()
    if note:
        print(note)
    memory = load_memory()

    if state is None or rng is None:
        use_tk = ("--console" not in flag_set) and ui.tk_available()
        # в окне сид не спрашиваем (в сборке без консоли input() невозможен): каждая кампания своя
        seed = random.SystemRandom().randint(1, 999999) if use_tk else _ask_seed_console()
        if use_tk:
            name, age = ui.ask_profile()
        else:
            name, age = _ask_profile_console()
        state, rng = new_game(data, seed, name, age)
        save_game(state, rng)
        print("Новая кампания. Сид: " + str(seed) + ". Имя: " + name + ", возраст: " + str(age) + ".")

    # A/B-выбор «парсер или НС» — только в плейтесте (config playtest_mode или флаг --playtest)
    state.ab_mode = playtest_on() and bool(data.nn.get("ab_mode", False) or "--playtest" in flag_set)
    use_tk = ("--console" not in flag_set) and ui.tk_available()
    if use_tk:
        tk_loop(state, rng, memory)
    else:
        console_loop(state, rng, memory)
        write_session_report(state)
    print("Отчёт сессии: " + str(SAVE_DIR / "playtest_report.txt") + " — пришли его автору вместе с feedback.txt.")
    return 0


def _fatal(text: str) -> None:
    """Сборка без консоли: ошибку нельзя напечатать — пишем crash.log и показываем окно."""
    try:
        ensure_dirs()
        (SAVE_DIR / "crash.log").write_text(text, encoding="utf-8")
    except Exception:
        pass
    if models.frozen_build():
        try:
            import tkinter
            from tkinter import messagebox
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("Кочто", text[-1500:] + "\n\nЛог: " + str(SAVE_DIR / "crash.log"))
            root.destroy()
        except Exception:
            pass


def run() -> int:
    import traceback
    try:
        code = main()
    except SystemExit:
        raise
    except Exception:
        _fatal("Игра упала:\n" + traceback.format_exc())
        return 1
    if code == 2:
        _fatal("Не удалось загрузить данные игры (папка data рядом с Kochto.exe). "
               "Распакуй архив целиком и запусти снова.")
    return code


if __name__ == "__main__":
    sys.exit(run())