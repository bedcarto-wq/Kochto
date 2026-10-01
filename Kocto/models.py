from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ================= пути (любой CWD; сборка PyInstaller; USER-папка отдельно от игры) =================
def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = _base_dir()
DATA_DIR = BASE_DIR / "data"          # контент игры (читается, не пишется в рантайме)


def frozen_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def _user_dir() -> Path:
    """Пользовательская папка: в сборке — отдельно от файлов игры; в разработке — рядом с кодом."""
    if frozen_build():
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", str(BASE_DIR)))
        else:
            base = Path.home()
        return base / "Kochto"
    return BASE_DIR

USER_DIR = _user_dir()
SAVE_DIR = USER_DIR / "saves"
# Diagnostic/eval/рантайм-файлы: в сборке живут отдельно от игры, в разработке — в data/
USER_DATA_DIR = (USER_DIR / "data") if frozen_build() else DATA_DIR


def data_path(*rel: str) -> Path:
    return DATA_DIR.joinpath(*rel)


def user_data_path(*rel: str) -> Path:
    return USER_DATA_DIR.joinpath(*rel)


def save_path(*rel: str) -> Path:
    return SAVE_DIR.joinpath(*rel)


# ================= параметры движка (НЕ контент; перенос в JSON сломал бы контракты) =================
WEEKLY_ACTION_LIMIT = 3
DETAIL_ALIASES = {
    "кратко": "кратко", "short": "кратко",
    "нормально": "нормально", "normal": "нормально",
    "полно": "полно", "full": "полно",
}
DETERMINISM_POLICIES = ("F", "entropy")   # в прототипе активна "F"; уход от детерминизма — после рецензий
SIMILARITY_THRESHOLD = 0.5               # >=50% n-gram пересечения с текстом за окно -> браковка
SIMILARITY_WINDOW_WEEKS = 5

# ================= рантайм/eval относительные пути (создаются в USER_DATA_DIR) =================
NN_MEMORY_CONSTRUCTIONS = "nn/memory/constructions.json"
NN_EVAL_AB = "nn/eval/ab_judgments.jsonl"
NN_EVAL_AB_SUMMARY = "nn/eval/ab_summary.json"
NN_EVAL_ANALYZER = "nn/eval/analyzer_judgments.jsonl"
NN_EVAL_PARSER_DEBUG = "nn/eval/parser_debug.jsonl"
LAWS_CUSTOM = "laws/custom_laws.json"


class DataError(Exception):
    """Адресная ошибка данных (R1/R2): отсутствует файл или обязательный ключ/тип."""


# ================= enum-контракты (структура состояния, не контент) =================
class ElectoralSystem(Enum):
    MAJORITARIAN = "мажоритарная"
    PROPORTIONAL = "пропорциональная"
    MIXED = "смешанная"


class Role(Enum):
    OUTSIDER = "outsider"
    CANDIDATE = "candidate"
    COUNCILOR = "councilor"
    MAYOR = "mayor"


class PrisonStatus(Enum):
    FREE = "free"
    UNDER_INVESTIGATION = "under_investigation"
    TRIAL = "trial"
    PRISON = "prison"
    DETAINED = "detained"
    ARRESTED = "arrested"
    ESCAPED = "escaped"
    FUGITIVE = "fugitive"


class ParseStatus(Enum):
    PARSED = "parsed"
    AMBIGUOUS = "ambiguous"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"
    NEEDS_CHOICE = "needs_choice"
    NEEDS_REFORMULATION = "needs_reformulation"
    TOO_MANY_ACTIONS = "too_many_actions"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    QUEUE_FULL = "queue_full"
    COOLDOWN = "cooldown"
    WEEK_LIMIT = "week_limit"


# ================= модели данных =================
@dataclass
class PlayerState:
    name: str = "Игрок"
    age: int = 35
    money: int = 100
    awareness: int = 10
    trust: int = 10
    anti_awareness: int = 5
    health: int = 80
    stress: int = 10
    fatigue: int = 5
    evidence: int = 0
    investigation: int = 0
    threat: int = 0
    escape_prep: int = 0
    prison_status: PrisonStatus = PrisonStatus.FREE
    charisma: int = 5
    persuasion: int = 5
    organization: int = 5
    media: int = 5
    administration: int = 5
    stealth: int = 5
    connections: int = 5
    security: int = 5
    role: Role = Role.CANDIDATE
    got_mandate: bool = False
    party_id: str = ""
    party_role: str = ""
    founded_party: bool = False
    legacy_tags: List[str] = field(default_factory=list)
    queued_delayed: List[str] = field(default_factory=list)


@dataclass
class VillageRuntime:
    # Метаданные АКТИВНОГО уровня (в прототипе — город; display_name декоративно меняет «деревня->город»)
    id: str = "kochto"
    name: str = "Кочто"
    display_name: str = "Кочто (город)"
    level: str = "city"
    population: int = 20000
    budget: int = 100


@dataclass
class GroupRuntime:
    id: str = ""
    name: str = ""
    size: int = 10                 # численность группы (для агрегации)
    mood: int = 50                 # индекс 0..100 (настроение, НЕ поддержка субъекта)
    loyalty: int = 50              # индекс 0..100
    issues: Dict[str, int] = field(default_factory=dict)
    # B-1: абсолютные сторонники субъектов (кандидаты/партии). Проценты per-level считаются на лету:
    # share = supporters / population_level * 100.
    candidate_support: Dict[str, int] = field(default_factory=dict)
    party_support: Dict[str, int] = field(default_factory=dict)


@dataclass
class PartyRuntime:
    id: str = ""
    name: str = ""
    popularity: int = 10
    trust_to_player: int = 10
    discipline: int = 50
    scandal: int = 0
    seats: int = 0


@dataclass
class CandidateRuntime:
    id: str = ""
    name: str = ""
    popularity: int = 10           # индекс 0..100 (узнаваемость/рейтинг, не абсолют)
    scandal: int = 0
    party_id: str = ""


@dataclass
class NpcRuntime:
    id: str = ""
    name: str = ""
    role: str = "староста"
    loyalty: int = 50
    influence: int = 10


@dataclass
class Publication:
    id: str = ""
    name: str = ""
    tone: float = 0.0
    reach: int = 10


@dataclass
class ActionData:
    id: str = ""
    title: str = ""
    description: str = ""
    intent: str = ""
    issue: str = ""
    target_candidate_id: str = ""
    target_group_id: str = ""
    delayed: bool = False
    cost: int = 0


@dataclass
class WeekFact:
    id: str = ""
    kind: str = "event"
    tone: float = 0.0
    text: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LevelState:
    # B2-α: симметричный контейнер уровня. В прототипе активен только city (прямые поля GameState);
    # region/federation — скелеты (active=False, коллекции пустые, тик и accessors под дерево отложены).
    # ДОЛГ: при оживлении региона перенести городские коллекции сюда и переключить accessors на
    # state.levels[state.active_level]. Сейчас это закладка, чтобы не менять модели позже.
    level_id: str = ""
    display_name: str = ""
    parent_id: str = ""
    children_ids: List[str] = field(default_factory=list)
    population: int = 0
    active: bool = False
    groups: List[GroupRuntime] = field(default_factory=list)
    parties: List[PartyRuntime] = field(default_factory=list)
    candidates: List[CandidateRuntime] = field(default_factory=list)
    npcs: List[NpcRuntime] = field(default_factory=list)
    publications: List[Publication] = field(default_factory=list)
    parliament_seats: Dict[str, int] = field(default_factory=dict)
    council_seats: int = 0
    treasury: int = 0


@dataclass
class GameState:
    seed: int = 20240101
    week: int = 1
    current_week: int = 1
    next_election_week: int = 10
    election_count: int = 0
    treasury: int = 100
    council_seats: int = 0
    electoral_system: ElectoralSystem = ElectoralSystem.MIXED
    actions_this_week: int = 0
    detail_level: str = "нормально"
    next_archive_no: int = 1
    rng_state: str = ""
    game_over_reason: str = ""
    is_game_over: bool = False
    determinism_policy: str = "F"
    free_generator: bool = False
    ab_mode: bool = True
    # --- B2-α закладка дерева уровней (активный уровень = прямые поля ниже; скелеты в levels) ---
    active_level: str = "city"
    levels: Dict[str, LevelState] = field(default_factory=dict)
    # --- активный уровень (город) ---
    player: PlayerState = field(default_factory=PlayerState)
    village: VillageRuntime = field(default_factory=VillageRuntime)
    groups: List[GroupRuntime] = field(default_factory=list)
    parties: List[PartyRuntime] = field(default_factory=list)
    candidates: List[CandidateRuntime] = field(default_factory=list)
    npcs: List[NpcRuntime] = field(default_factory=list)
    publications: List[Publication] = field(default_factory=list)
    parliament_seats: Dict[str, int] = field(default_factory=dict)
    week_actions: List[Dict[str, Any]] = field(default_factory=list)
    week_seeds: List[int] = field(default_factory=list)
    custom_laws: List[Dict[str, Any]] = field(default_factory=list)
    news_feed: List[Dict[str, Any]] = field(default_factory=list)
    clippings: List[Dict[str, Any]] = field(default_factory=list)
    bills: List[Dict[str, Any]] = field(default_factory=list)
    enacted_laws: List[Dict[str, Any]] = field(default_factory=list)
    promises: List[Dict[str, Any]] = field(default_factory=list)
    event_log: List[str] = field(default_factory=list)
    parser_context: Dict[str, Any] = field(default_factory=dict)
    text_history: List[Dict[str, Any]] = field(default_factory=list)  # для уникальности за 5 недель


@dataclass
class GameData:
    village: Dict[str, Any]
    groups: List[Dict[str, Any]]
    parties: List[Dict[str, Any]]
    candidates: List[Dict[str, Any]]
    npcs: List[Dict[str, Any]]
    publications: List[Dict[str, Any]]
    councils: Dict[str, Any]
    start: Dict[str, Any]
    balance: Dict[str, Any]
    dictionaries: Dict[str, Any]
    intents: Dict[str, Any]            # Q-C: отдельный реестр типов intent
    nn: Dict[str, Any]
    templates: Dict[str, Any]
    actions: List[Dict[str, Any]]
    electoral: Dict[str, Any]
    laws: Dict[str, Any]
    events: Dict[str, Any]
    promises: Dict[str, Any]
    budget: Dict[str, Any]
    region: Dict[str, Any] = field(default_factory=dict)       # метаданные скелета региона
    federation: Dict[str, Any] = field(default_factory=dict)   # метаданные скелета федерации


# ================= JSON IO =================
def _read_json(path: Path, what: str) -> Any:
    if not path.exists():
        raise DataError(f"Отсутствует обязательный файл данных: {path} ({what}).")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DataError(f"Повреждён файл данных: {path} ({exc}).")


def _read_optional(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_json(path: Path, default: Any) -> Any:
    return _read_optional(path, default)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# ================= валидатор структуры (R2): адресная ошибка по ключу/типу =================
def _need_map(data: Any, where: str) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise DataError(f"{where}: ожидался объект JSON, получено {type(data).__name__}.")
    return data


def _need_list(data: Any, where: str) -> List[Any]:
    if not isinstance(data, list):
        raise DataError(f"{where}: ожидался массив JSON, получено {type(data).__name__}.")
    return data


def _need_keys(obj: Dict[str, Any], keys: Tuple[str, ...], where: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise DataError(f"{where}: отсутствуют обязательные ключи: {', '.join(missing)}.")


def _validate_scenario(raw: Any, where: str) -> Dict[str, Any]:
    d = _need_map(raw, where)
    _need_keys(d, ("village", "groups", "parties", "candidates", "npcs", "publications", "councils", "start", "balance"), where)
    _need_map(d["village"], f"{where}.village")
    _need_list(d["groups"], f"{where}.groups")
    _need_list(d["parties"], f"{where}.parties")
    _need_list(d["candidates"], f"{where}.candidates")
    _need_list(d["npcs"], f"{where}.npcs")
    _need_list(d["publications"], f"{where}.publications")
    return d


def _validate_dictionaries(raw: Any, where: str) -> Dict[str, Any]:
    d = _need_map(raw, where)
    _need_keys(d, ("schema_version", "verbs", "groups", "issues", "modality", "negation", "stopwords"), where)
    return d


def _validate_intents(raw: Any, where: str) -> Dict[str, Any]:
    d = _need_map(raw, where)
    _need_keys(d, ("schema_version", "intents"), where)
    items = _need_list(d["intents"], f"{where}.intents")
    if not items:
        raise DataError(f"{where}.intents: пустой реестр типов — парсеру нечего распознавать.")
    for i, it in enumerate(items):
        m = _need_map(it, f"{where}.intents[{i}]")
        _need_keys(m, ("intent_id", "label", "verbs"), f"{where}.intents[{i}]")
        _need_list(m["verbs"], f"{where}.intents[{i}].verbs")
    return d


def _validate_templates(raw: Any, where: str) -> Dict[str, Any]:
    d = _need_map(raw, where)
    _need_keys(d, ("schema_version", "headlines", "bodies"), where)
    return d


def _validate_config(raw: Any, where: str) -> Dict[str, Any]:
    d = _need_map(raw, where)
    _need_keys(d, ("schema_version", "determinism_policy", "ab_mode", "free_generator",
                   "enabled_recognizer", "enabled_writer", "enabled_analyzer"), where)
    if d["determinism_policy"] not in DETERMINISM_POLICIES:
        raise DataError(f"{where}.determinism_policy: неизвестная политика {d['determinism_policy']!r}, "
                        f"допустимо {DETERMINISM_POLICIES}.")
    return d


def _validate_nn_section(raw: Any, where: str, required_top: Tuple[str, ...]) -> Dict[str, Any]:
    d = _need_map(raw, where)
    _need_keys(d, required_top, where)
    return d


# ================= загрузчик данных (R1: отсутствие обязательного = ошибка; необязательное = warning) =================
def load_data(data_dir: Path, active_scenario: str = "city.json") -> Tuple[GameData, List[str]]:
    warnings: List[str] = []

    scenario = _validate_scenario(_read_json(data_dir / "scenarios" / active_scenario, "сценарий активного уровня"),
                                  "scenarios/" + active_scenario)

    dictionaries = _validate_dictionaries(_read_json(data_dir / "parser" / "dictionaries.json", "словари парсера"),
                                          "parser/dictionaries.json")
    intents = _validate_intents(_read_json(data_dir / "intents" / "intents.json", "реестр типов intent"),
                                "intents/intents.json")
    templates = _validate_templates(_read_json(data_dir / "text" / "templates.json", "шаблоны текстов"),
                                    "text/templates.json")
    config = _validate_config(_read_json(data_dir / "nn" / "config.json", "конфиг НС"), "nn/config.json")

    actions_raw = _read_json(data_dir / "actions" / "actions.json", "каталог действий")
    actions_map = _need_map(actions_raw, "actions/actions.json")
    actions = _need_list(actions_map.get("actions"), "actions/actions.json.actions")
    if not actions:
        raise DataError("actions/actions.json.actions: пустой каталог — играть нечем.")

    enabled_rec = bool(config.get("enabled_recognizer", False))
    enabled_wr = bool(config.get("enabled_writer", False))
    enabled_an = bool(config.get("enabled_analyzer", False))

    weights: Dict[str, Any] = {}
    if enabled_rec or enabled_wr:
        wpath = data_dir / "nn" / "weights.json"
        if not wpath.exists():
            raise DataError(f"Отсутствует nn/weights.json, но enabled_recognizer/enabled_writer включены. "
                            f"Создай файл или выставь флаги в false в nn/config.json.")
        weights = _need_map(_read_json(wpath, "веса НС"), "nn/weights.json")
    else:
        weights = _read_optional(data_dir / "nn" / "weights.json", {}) or {}
        if not weights:
            warnings.append("nn/weights.json отсутствует, но все НС-флаги выключены — НС не грузится.")

    lexicons: Dict[str, Any] = {}
    if enabled_wr:
        lpath = data_dir / "nn" / "lexicons.json"
        if not lpath.exists():
            raise DataError("Отсутствует nn/lexicons.json, но enabled_writer включён. "
                            "Создай файл или выставь enabled_writer=false в nn/config.json.")
        lexicons = _validate_nn_section(_read_json(lpath, "лексиконы писателя"), "nn/lexicons.json",
                                        ("schema_version", "registers", "substitutes", "consequences", "reactions"))
    else:
        lexicons = _read_optional(data_dir / "nn" / "lexicons.json", {}) or {}

    analyzer_cfg: Dict[str, Any] = {}
    if enabled_an:
        apath = data_dir / "nn" / "analyzer.json"
        if not apath.exists():
            raise DataError("Отсутствует nn/analyzer.json, но enabled_analyzer включён. "
                            "Создай файл или выставь enabled_analyzer=false в nn/config.json.")
        analyzer_cfg = _validate_nn_section(_read_json(apath, "конфиг анализатора"), "nn/analyzer.json",
                                            ("schema_version", "tier_distribution_prior", "context_weights",
                                             "reaction_tables"))
    else:
        analyzer_cfg = _read_optional(data_dir / "nn" / "analyzer.json", {}) or {}

    recognizer_cfg = weights.get("recognizer", {}) if isinstance(weights, dict) else {}

    nn = {
        "config": config,
        "weights": weights,
        "lexicons": lexicons,
        "analyzer": analyzer_cfg,
        "recognizer": recognizer_cfg,
        "ab_mode": bool(config.get("ab_mode", True)),
        "free_generator": bool(config.get("free_generator", False)),
        "determinism_policy": str(config.get("determinism_policy", "F")),
        "enabled_recognizer": enabled_rec,
        "enabled_writer": enabled_wr,
        "enabled_analyzer": enabled_an,
        "min_confidence_default": float(config.get("min_confidence_default", 0.45)),
    }

    # необязательные файлы -> warning при отсутствии, не краш
    electoral = _read_optional(data_dir / "electoral" / "systems.json", {}) or {}
    laws_main = _read_optional(data_dir / "laws" / "laws.json", {}) or {}
    laws_hierarchy = _read_optional(data_dir / "laws" / "hierarchy.json", {}) or {}
    laws_domains = _read_optional(data_dir / "laws" / "domains.json", {}) or {}
    laws = {
        "templates": laws_main.get("templates", []),
        "act_types": laws_main.get("act_types", laws_hierarchy.get("act_types", {})),
        "veto": laws_main.get("veto", laws_hierarchy.get("veto", {})),
        "domains": laws_domains.get("domains", laws_main.get("domains", [])),
        "legal_predicates": laws_main.get("legal_predicates", dictionaries.get("legal_predicates", [])),
    }
    if enabled_an and not laws["legal_predicates"]:
        warnings.append("Для свободных законов (law_custom) нужны legal_predicates в laws.json или dictionaries.json.")
    events = _read_optional(data_dir / "events" / "village_events.json", {}) or {}
    promises = _read_optional(data_dir / "promises" / "rules.json", {}) or {}
    budget = _read_optional(data_dir / "budget" / "constants.json", {}) or {}

    # скелеты верхних уровней (B2-α): читаем метаданные если файлы есть; иначе пустой скелет + warning
    region = _read_optional(data_dir / "scenarios" / "region.json", {}) or {}
    federation = _read_optional(data_dir / "scenarios" / "federation.json", {}) or {}
    if not region:
        warnings.append("scenarios/region.json отсутствует — регион остаётся пустым скелетом (не тикает).")
    if not federation:
        warnings.append("scenarios/federation.json отсутствует — федерация остаётся пустым скелетом (не тикает).")

    data = GameData(
        village=scenario.get("village", {}),
        groups=scenario.get("groups", []),
        parties=scenario.get("parties", []),
        candidates=scenario.get("candidates", []),
        npcs=scenario.get("npcs", []),
        publications=scenario.get("publications", []),
        councils=scenario.get("councils", {}),
        start=scenario.get("start", {}),
        balance=scenario.get("balance", {}),
        dictionaries=dictionaries,
        intents=intents,
        nn=nn,
        templates=templates,
        actions=actions,
        electoral=electoral,
        laws=laws,
        events=events,
        promises=promises,
        budget=budget,
        region=region,
        federation=federation,
    )
    return data, warnings


# ================= рантайм-файлы (создаются в USER_DATA_DIR; в сборке отдельно от игры) =================
def ensure_runtime_files(data_dir: Optional[Path] = None) -> List[str]:
    target = data_dir or USER_DATA_DIR
    warnings: List[str] = []
    skeletons = {
        NN_MEMORY_CONSTRUCTIONS: {"constructions": []},
        NN_EVAL_AB_SUMMARY: {"parser_wins": 0, "nn_wins": 0, "consensus": 0, "refusals": 0, "by_intent": {}},
        LAWS_CUSTOM: {"laws": []},
    }
    jsonl_files = [NN_EVAL_AB, NN_EVAL_ANALYZER, NN_EVAL_PARSER_DEBUG]
    for rel, default in skeletons.items():
        path = target / rel
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            warnings.append(f"Не удалось создать {path}: {exc}")
    for rel in jsonl_files:
        path = target / rel
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("", encoding="utf-8")
        except Exception as exc:
            warnings.append(f"Не удалось создать {path}: {exc}")
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        warnings.append(f"Не удалось создать {SAVE_DIR}: {exc}")
    return warnings


# ================= сборка состояния из данных =================
def _level_skeleton(meta: Dict[str, Any], level_id: str, default_name: str) -> LevelState:
    if not meta:
        return LevelState(level_id=level_id, display_name=default_name, population=0, active=False)
    return LevelState(
        level_id=str(meta.get("id", level_id)),
        display_name=str(meta.get("display_name", meta.get("name", default_name))),
        parent_id=str(meta.get("parent", "")),
        children_ids=[str(c) for c in meta.get("children", [])],
        population=int(meta.get("population", 0)),
        active=False,
    )


def build_state(data: GameData, seed: int) -> GameState:
    state = GameState(seed=seed)
    v = data.village
    state.village = VillageRuntime(
        id=str(v.get("id", "kochto")),
        name=str(v.get("name", "Кочто")),
        display_name=str(v.get("display_name", v.get("name", "Кочто (город)"))),
        level=str(v.get("level", "city")),
        population=int(v.get("population", 20000)),
        budget=int(v.get("budget", 100)),
    )
    state.treasury = int(data.start.get("treasury", state.village.budget))
    state.groups = [
        GroupRuntime(
            id=str(g.get("id", "")), name=str(g.get("name", "")), size=int(g.get("size", 10)),
            mood=int(g.get("mood", 50)), loyalty=int(g.get("loyalty", 50)),
            issues=dict(g.get("issues", {})),
            candidate_support={str(k): int(x) for k, x in (g.get("candidate_support") or {}).items()},
            party_support={str(k): int(x) for k, x in (g.get("party_support") or {}).items()},
        ) for g in data.groups
    ]
    state.parties = [
        PartyRuntime(id=str(p.get("id", "")), name=str(p.get("name", "")), popularity=int(p.get("popularity", 10)),
                     trust_to_player=int(p.get("trust_to_player", 10)), discipline=int(p.get("discipline", 50)),
                     scandal=int(p.get("scandal", 0)), seats=int(p.get("seats", 0))) for p in data.parties
    ]
    state.candidates = [
        CandidateRuntime(id=str(c.get("id", "")), name=str(c.get("name", "")), popularity=int(c.get("popularity", 10)),
                         scandal=int(c.get("scandal", 0)), party_id=str(c.get("party_id", ""))) for c in data.candidates
    ]
    state.npcs = [
        NpcRuntime(id=str(n.get("id", "")), name=str(n.get("name", "")), role=str(n.get("role", "староста")),
                   loyalty=int(n.get("loyalty", 50)), influence=int(n.get("influence", 10))) for n in data.npcs
    ]
    state.publications = [
        Publication(id=str(p.get("id", "")), name=str(p.get("name", "")), tone=float(p.get("tone", 0.0)),
                    reach=int(p.get("reach", 10))) for p in data.publications
    ]
    state.parliament_seats = {p.id: p.seats for p in state.parties}
    state.parliament_seats["player"] = 0

    # B2-α: скелеты верхних уровней + дерево (активный уровень = город = прямые поля выше)
    city_level = LevelState(
        level_id="city", display_name=state.village.display_name,
        parent_id=str(data.region.get("id", "")) if data.region else "",
        children_ids=[], population=state.village.population, active=True,
    )
    region_level = _level_skeleton(data.region, "region", "Регион")
    federation_level = _level_skeleton(data.federation, "federation", "Федерация")
    # свяжем дерево: federation -> region -> city (если метаданные заданы)
    if region_level.level_id:
        city_level.parent_id = region_level.level_id
        if city_level.level_id not in region_level.children_ids:
            region_level.children_ids.append(city_level.level_id)
    if federation_level.level_id and region_level.level_id:
        region_level.parent_id = federation_level.level_id
        if region_level.level_id not in federation_level.children_ids:
            federation_level.children_ids.append(region_level.level_id)
    state.levels = {"city": city_level, "region": region_level, "federation": federation_level}
    state.active_level = "city"

    st = data.start
    pl = state.player
    pl.name = str(st.get("player_name", pl.name))
    pl.age = int(st.get("age", pl.age))
    pl.money = int(st.get("money", pl.money))
    pl.awareness = int(st.get("awareness", pl.awareness))
    pl.trust = int(st.get("trust", pl.trust))
    pl.anti_awareness = int(st.get("anti_awareness", pl.anti_awareness))
    if st.get("role") in [r.value for r in Role]:
        pl.role = Role(st["role"])
    if st.get("electoral_system") in [e.value for e in ElectoralSystem]:
        state.electoral_system = ElectoralSystem(st["electoral_system"])
    state.next_election_week = int(st.get("first_election_week", 10))
    state.determinism_policy = data.nn.get("determinism_policy", "F")
    state.free_generator = bool(data.nn.get("free_generator", False))
    state.ab_mode = bool(data.nn.get("ab_mode", True))
    return state


# ================= сериализация =================
def _group_to_dict(g: GroupRuntime) -> Dict[str, Any]:
    return {"id": g.id, "name": g.name, "size": g.size, "mood": g.mood, "loyalty": g.loyalty,
            "issues": dict(g.issues), "candidate_support": dict(g.candidate_support),
            "party_support": dict(g.party_support)}


def _group_from_dict(d: Dict[str, Any]) -> GroupRuntime:
    return GroupRuntime(id=str(d.get("id", "")), name=str(d.get("name", "")), size=int(d.get("size", 10)),
                        mood=int(d.get("mood", 50)), loyalty=int(d.get("loyalty", 50)),
                        issues=dict(d.get("issues", {})),
                        candidate_support={str(k): int(x) for k, x in (d.get("candidate_support") or {}).items()},
                        party_support={str(k): int(x) for k, x in (d.get("party_support") or {}).items()})


def _level_to_dict(l: LevelState) -> Dict[str, Any]:
    return {"level_id": l.level_id, "display_name": l.display_name, "parent_id": l.parent_id,
            "children_ids": list(l.children_ids), "population": l.population, "active": l.active,
            "groups": [_group_to_dict(g) for g in l.groups],
            "parties": [{"id": p.id, "name": p.name, "popularity": p.popularity, "trust_to_player": p.trust_to_player,
                         "discipline": p.discipline, "scandal": p.scandal, "seats": p.seats} for p in l.parties],
            "candidates": [{"id": c.id, "name": c.name, "popularity": c.popularity, "scandal": c.scandal,
                            "party_id": c.party_id} for c in l.candidates],
            "npcs": [{"id": n.id, "name": n.name, "role": n.role, "loyalty": n.loyalty, "influence": n.influence}
                     for n in l.npcs],
            "publications": [{"id": p.id, "name": p.name, "tone": p.tone, "reach": p.reach} for p in l.publications],
            "parliament_seats": dict(l.parliament_seats), "council_seats": l.council_seats, "treasury": l.treasury}


def _level_from_dict(d: Dict[str, Any]) -> LevelState:
    return LevelState(
        level_id=str(d.get("level_id", "")), display_name=str(d.get("display_name", "")),
        parent_id=str(d.get("parent_id", "")), children_ids=[str(c) for c in d.get("children_ids", [])],
        population=int(d.get("population", 0)), active=bool(d.get("active", False)),
        groups=[_group_from_dict(g) for g in d.get("groups", [])],
        parties=[PartyRuntime(id=str(p.get("id", "")), name=str(p.get("name", "")), popularity=int(p.get("popularity", 10)),
                              trust_to_player=int(p.get("trust_to_player", 10)), discipline=int(p.get("discipline", 50)),
                              scandal=int(p.get("scandal", 0)), seats=int(p.get("seats", 0))) for p in d.get("parties", [])],
        candidates=[CandidateRuntime(id=str(c.get("id", "")), name=str(c.get("name", "")), popularity=int(c.get("popularity", 10)),
                                     scandal=int(c.get("scandal", 0)), party_id=str(c.get("party_id", ""))) for c in d.get("candidates", [])],
        npcs=[NpcRuntime(id=str(n.get("id", "")), name=str(n.get("name", "")), role=str(n.get("role", "староста")),
                         loyalty=int(n.get("loyalty", 50)), influence=int(n.get("influence", 10))) for n in d.get("npcs", [])],
        publications=[Publication(id=str(p.get("id", "")), name=str(p.get("name", "")), tone=float(p.get("tone", 0.0)),
                                  reach=int(p.get("reach", 10))) for p in d.get("publications", [])],
        parliament_seats=dict(d.get("parliament_seats", {})), council_seats=int(d.get("council_seats", 0)),
        treasury=int(d.get("treasury", 0)),
    )


def game_to_dict(state: GameState) -> Dict[str, Any]:
    return {
        "seed": state.seed, "week": state.week, "current_week": state.current_week,
        "next_election_week": state.next_election_week, "election_count": state.election_count,
        "treasury": state.treasury, "council_seats": state.council_seats,
        "electoral_system": state.electoral_system.value,
        "actions_this_week": state.actions_this_week, "detail_level": state.detail_level,
        "next_archive_no": state.next_archive_no, "rng_state": state.rng_state,
        "game_over_reason": state.game_over_reason, "is_game_over": state.is_game_over,
        "determinism_policy": state.determinism_policy, "free_generator": state.free_generator,
        "ab_mode": state.ab_mode, "active_level": state.active_level,
        "levels": {k: _level_to_dict(v) for k, v in state.levels.items()},
        "player": {
            "name": state.player.name, "age": state.player.age, "money": state.player.money,
            "awareness": state.player.awareness, "trust": state.player.trust,
            "anti_awareness": state.player.anti_awareness, "health": state.player.health,
            "stress": state.player.stress, "fatigue": state.player.fatigue,
            "evidence": state.player.evidence, "investigation": state.player.investigation,
            "threat": state.player.threat, "escape_prep": state.player.escape_prep,
            "prison_status": state.player.prison_status.value,
            "charisma": state.player.charisma, "persuasion": state.player.persuasion,
            "organization": state.player.organization, "media": state.player.media,
            "administration": state.player.administration, "stealth": state.player.stealth,
            "connections": state.player.connections, "security": state.player.security,
            "role": state.player.role.value, "got_mandate": state.player.got_mandate,
            "party_id": state.player.party_id, "party_role": state.player.party_role,
            "founded_party": state.player.founded_party, "legacy_tags": list(state.player.legacy_tags),
            "queued_delayed": list(state.player.queued_delayed),
        },
        "village": {"id": state.village.id, "name": state.village.name, "display_name": state.village.display_name,
                    "level": state.village.level, "population": state.village.population, "budget": state.village.budget},
        "groups": [_group_to_dict(g) for g in state.groups],
        "parties": [{"id": p.id, "name": p.name, "popularity": p.popularity, "trust_to_player": p.trust_to_player,
                     "discipline": p.discipline, "scandal": p.scandal, "seats": p.seats} for p in state.parties],
        "candidates": [{"id": c.id, "name": c.name, "popularity": c.popularity, "scandal": c.scandal,
                        "party_id": c.party_id} for c in state.candidates],
        "npcs": [{"id": n.id, "name": n.name, "role": n.role, "loyalty": n.loyalty, "influence": n.influence}
                 for n in state.npcs],
        "publications": [{"id": p.id, "name": p.name, "tone": p.tone, "reach": p.reach} for p in state.publications],
        "parliament_seats": dict(state.parliament_seats),
        "week_actions": list(state.week_actions), "week_seeds": list(state.week_seeds),
        "custom_laws": list(state.custom_laws), "news_feed": list(state.news_feed),
        "clippings": list(state.clippings), "bills": list(state.bills), "enacted_laws": list(state.enacted_laws),
        "promises": list(state.promises), "event_log": list(state.event_log),
        "parser_context": dict(state.parser_context), "text_history": list(state.text_history),
    }


def game_from_dict(data: Dict[str, Any]) -> GameState:
    state = GameState()
    state.seed = int(data.get("seed", state.seed))
    state.week = int(data.get("week", 1))
    state.current_week = int(data.get("current_week", state.week))
    state.next_election_week = int(data.get("next_election_week", 10))
    state.election_count = int(data.get("election_count", 0))
    state.treasury = int(data.get("treasury", state.treasury))
    state.council_seats = int(data.get("council_seats", 0))
    state.electoral_system = ElectoralSystem(data.get("electoral_system", state.electoral_system.value))
    state.actions_this_week = int(data.get("actions_this_week", 0))
    state.detail_level = str(data.get("detail_level", "нормально"))
    state.next_archive_no = int(data.get("next_archive_no", 1))
    state.rng_state = str(data.get("rng_state", ""))
    state.game_over_reason = str(data.get("game_over_reason", ""))
    state.is_game_over = bool(data.get("is_game_over", False))
    state.determinism_policy = str(data.get("determinism_policy", "F"))
    state.free_generator = bool(data.get("free_generator", False))
    state.ab_mode = bool(data.get("ab_mode", True))
    state.active_level = str(data.get("active_level", "city"))
    state.levels = {k: _level_from_dict(v) for k, v in (data.get("levels") or {}).items()}
    pd = data.get("player", {})
    pl = state.player
    pl.name = str(pd.get("name", pl.name)); pl.age = int(pd.get("age", pl.age)); pl.money = int(pd.get("money", pl.money))
    pl.awareness = int(pd.get("awareness", pl.awareness)); pl.trust = int(pd.get("trust", pl.trust))
    pl.anti_awareness = int(pd.get("anti_awareness", pl.anti_awareness)); pl.health = int(pd.get("health", pl.health))
    pl.stress = int(pd.get("stress", pl.stress)); pl.fatigue = int(pd.get("fatigue", pl.fatigue))
    pl.evidence = int(pd.get("evidence", pl.evidence)); pl.investigation = int(pd.get("investigation", pl.investigation))
    pl.threat = int(pd.get("threat", pl.threat)); pl.escape_prep = int(pd.get("escape_prep", pl.escape_prep))
    pl.prison_status = PrisonStatus(pd.get("prison_status", pl.prison_status.value))
    pl.charisma = int(pd.get("charisma", pl.charisma)); pl.persuasion = int(pd.get("persuasion", pl.persuasion))
    pl.organization = int(pd.get("organization", pl.organization)); pl.media = int(pd.get("media", pl.media))
    pl.administration = int(pd.get("administration", pl.administration)); pl.stealth = int(pd.get("stealth", pl.stealth))
    pl.connections = int(pd.get("connections", pl.connections)); pl.security = int(pd.get("security", pl.security))
    pl.role = Role(pd.get("role", pl.role.value)); pl.got_mandate = bool(pd.get("got_mandate", False))
    pl.party_id = str(pd.get("party_id", "")); pl.party_role = str(pd.get("party_role", ""))
    pl.founded_party = bool(pd.get("founded_party", False)); pl.legacy_tags = list(pd.get("legacy_tags", []))
    pl.queued_delayed = list(pd.get("queued_delayed", []))
    vd = data.get("village", {})
    state.village = VillageRuntime(id=str(vd.get("id", "kochto")), name=str(vd.get("name", "Кочто")),
                                   display_name=str(vd.get("display_name", vd.get("name", "Кочто (город)"))),
                                   level=str(vd.get("level", "city")), population=int(vd.get("population", 20000)),
                                   budget=int(vd.get("budget", 100)))
    state.groups = [_group_from_dict(g) for g in data.get("groups", [])]
    state.parties = [PartyRuntime(id=str(p.get("id", "")), name=str(p.get("name", "")), popularity=int(p.get("popularity", 10)),
                                  trust_to_player=int(p.get("trust_to_player", 10)), discipline=int(p.get("discipline", 50)),
                                  scandal=int(p.get("scandal", 0)), seats=int(p.get("seats", 0))) for p in data.get("parties", [])]
    state.candidates = [CandidateRuntime(id=str(c.get("id", "")), name=str(c.get("name", "")), popularity=int(c.get("popularity", 10)),
                                         scandal=int(c.get("scandal", 0)), party_id=str(c.get("party_id", ""))) for c in data.get("candidates", [])]
    state.npcs = [NpcRuntime(id=str(n.get("id", "")), name=str(n.get("name", "")), role=str(n.get("role", "староста")),
                             loyalty=int(n.get("loyalty", 50)), influence=int(n.get("influence", 10))) for n in data.get("npcs", [])]
    state.publications = [Publication(id=str(p.get("id", "")), name=str(p.get("name", "")), tone=float(p.get("tone", 0.0)),
                                      reach=int(p.get("reach", 10))) for p in data.get("publications", [])]
    state.parliament_seats = dict(data.get("parliament_seats", {p.id: p.seats for p in state.parties}))
    state.parliament_seats.setdefault("player", 0)
    state.week_actions = list(data.get("week_actions", []))
    state.week_seeds = list(data.get("week_seeds", []))
    state.custom_laws = list(data.get("custom_laws", []))
    state.news_feed = list(data.get("news_feed", []))
    state.clippings = list(data.get("clippings", []))
    state.bills = list(data.get("bills", []))
    state.enacted_laws = list(data.get("enacted_laws", []))
    state.promises = list(data.get("promises", []))
    state.event_log = list(data.get("event_log", []))
    state.parser_context = dict(data.get("parser_context", {}))
    state.text_history = list(data.get("text_history", []))
    return state