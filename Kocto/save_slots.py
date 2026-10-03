"""Named campaign slots with atomic checkpoints and one previous checkpoint.

Only the campaign store writes here. Character names are display labels, never
filenames. No pickle, external packages or automatic destructive recovery.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FORMAT = 'kochto.campaign.1'
ID_RE = re.compile(r'^[a-f0-9]{32}$')


class SaveError(ValueError):
    pass


class IncompatibleSave(SaveError):
    pass


@dataclass(frozen=True)
class SlotInfo:
    slot_id: str
    name: str
    week: int | None
    role: str
    saved_at: str
    status: str
    has_backup: bool


class SaveStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, slot_id: str, backup=False) -> Path:
        if not isinstance(slot_id, str) or not ID_RE.fullmatch(slot_id):
            raise SaveError('Некорректное сохранение.')
        path = self.root / (slot_id + ('.previous.json' if backup else '.json'))
        if path.is_symlink():
            raise SaveError('Сохранение не может быть символической ссылкой.')
        return path

    @staticmethod
    def _decode(raw: str, slot_id: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise SaveError('Файл сохранения повреждён.') from exc
        if not isinstance(value, dict):
            raise SaveError('Файл сохранения должен содержать объект.')
        if value.get('format') != FORMAT:
            raise IncompatibleSave('Сохранение другой версии.')
        if value.get('slot_id') != slot_id:
            raise SaveError('Содержимое не соответствует выбранному сохранению.')
        game = value.get('game')
        if not isinstance(game, dict) or not isinstance(game.get('player'), dict):
            raise SaveError('В сохранении нет состояния персонажа.')
        if type(game.get('week')) is not int or game['week'] < 1:
            raise SaveError('Некорректная игровая неделя.')
        if not isinstance(game['player'].get('name'), str) or not game['player']['name'].strip():
            raise SaveError('Не указано имя персонажа.')
        if not isinstance(value.get('name'), str) or not value['name'].strip():
            raise SaveError('Не указано название сохранения.')
        try:
            stamp = datetime.fromisoformat(value['saved_at'])
            if stamp.tzinfo is None:
                raise ValueError('timestamp must include timezone')
        except (ValueError, KeyError, TypeError) as exc:
            raise SaveError('Некорректная дата сохранения.') from exc
        return value

    def _read(self, slot_id: str, backup=False) -> dict[str, Any]:
        path = self._path(slot_id, backup)
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            raise SaveError('Не удалось прочитать сохранение.') from exc
        return self._decode(text, slot_id)

    def _atomic_write(self, path: Path, text: str):
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.checkpoint-', suffix='.tmp', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _encode(value):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        except (TypeError, ValueError) as exc:
            raise SaveError('Состояние игры нельзя сохранить в JSON.') from exc

    def create(self, game: dict[str, Any], slot_id: str | None = None) -> str:
        slot_id = uuid.uuid4().hex if slot_id is None else slot_id
        path = self._path(slot_id)
        if path.exists() or self._path(slot_id, True).exists():
            raise SaveError('Это сохранение уже существует; оно не будет перезаписано.')
        base = str((game.get('player') or {}).get('name', '')).strip()
        if not base:
            raise SaveError('Для сохранения нужно имя персонажа.')
        names = {info.name for info in self.list_slots()}
        name = base
        number = 2
        while name in names:
            name = f'{base} ({number})'
            number += 1
        envelope = self._envelope(slot_id, name, game)
        text = self._encode(envelope)
        self._decode(text, slot_id)
        self._atomic_write(path, text)
        return slot_id

    @staticmethod
    def _envelope(slot_id, name, game):
        return {'format': FORMAT, 'slot_id': slot_id, 'name': name,
                'saved_at': datetime.now(timezone.utc).isoformat(),
                'game': copy.deepcopy(game)}

    def save(self, slot_id: str, game: dict[str, Any]):
        old = self._read(slot_id)
        # Corrupt current files are NEVER copied over a good backup.
        # Recovery must be explicitly chosen before another write.
        previous_week = old['game']['week']
        envelope = self._envelope(slot_id, old['name'], game)
        text = self._encode(envelope)
        self._decode(text, slot_id)
        if game['week'] <= previous_week:
            raise SaveError('Автосохранение допускается только после новой завершённой недели.')
        self._atomic_write(self._path(slot_id, True), self._encode(old))
        self._atomic_write(self._path(slot_id), text)

    def load(self, slot_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._read(slot_id)['game'])

    def load_backup(self, slot_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._read(slot_id, True)['game'])

    def restore(self, slot_id: str):
        previous = self._read(slot_id, True)
        # Keep the valid backup intact and don't replace it with the corrupt file.
        self._atomic_write(self._path(slot_id), self._encode(previous))

    def delete(self, slot_id: str, *, confirmed=False):
        if confirmed is not True:
            raise SaveError('Удаление нужно подтвердить.')
        paths = [self._path(slot_id), self._path(slot_id, True), self.root / (slot_id + '.memory.json')]
        # Validate paths before deleting any files.
        if any(path.is_symlink() for path in paths):
            raise SaveError('Удаление символических ссылок запрещено.')
        for path in paths:
            path.unlink(missing_ok=True)

    def list_slots(self) -> list[SlotInfo]:
        if not self.root.exists():
            return []
        result = []
        for path in self.root.glob('*.json'):
            slot_id = path.stem
            if not ID_RE.fullmatch(slot_id):
                continue  # excludes backups, per-campaign memory and temp files
            backup = False
            try:
                self._read(slot_id, True)
                backup = True
            except SaveError:
                pass
            try:
                value = self._read(slot_id)
                game = value['game']
                status = 'dead' if game.get('is_game_over') and game.get('game_over_reason') == 'death' else 'alive'
                result.append(SlotInfo(slot_id, value['name'], game['week'],
                                       str(game['player'].get('role', '')), value['saved_at'], status, backup))
            except IncompatibleSave:
                result.append(SlotInfo(slot_id, 'Другая версия', None, '', '', 'incompatible', backup))
            except SaveError:
                result.append(SlotInfo(slot_id, 'Повреждённое сохранение', None, '', '', 'broken', backup))
        return sorted(result, key=lambda info: info.saved_at, reverse=True)
