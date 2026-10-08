"""Direct TCP link for two trusted friends. Stdlib only.

No relay, discovery service, telemetry, pickle, eval or remote file commands.
Authentication/integrity: random shared code, mutual challenge and HMAC-SHA256
on every sequenced packet. Contents are NOT encrypted: use a trusted LAN/VPN.
Network threads never touch Tk or game state: they exchange bounded queues.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import queue
import secrets
import socket
import struct
import threading

from . import __version__

PROTOCOL = 1
DEFAULT_PORT = 47606
MAX_PACKET = 4 * 1024 * 1024


class NetworkError(Exception):
    pass


def dumps(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _exact(sock, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size-len(chunks))
        if not chunk:
            raise NetworkError('Другой игрок отключился')
        chunks.extend(chunk)
    return bytes(chunks)


def send_raw(sock, obj):
    raw = dumps(obj)
    if len(raw) > MAX_PACKET:
        raise NetworkError('Состояние слишком велико для сетевого пакета. Сохраните партию.')
    sock.sendall(struct.pack('!I', len(raw)) + raw)


def recv_raw(sock):
    length = struct.unpack('!I', _exact(sock, 4))[0]
    if not 0 < length <= MAX_PACKET:
        raise NetworkError('Недопустимый размер сетевого пакета')
    try:
        obj = json.loads(_exact(sock, length).decode('utf-8'),
                         parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise NetworkError('Неверный JSON сетевого пакета') from exc
    if not isinstance(obj, dict):
        raise NetworkError('Ожидался объект сетевого пакета')
    return obj


def new_code():
    return secrets.token_hex(16)


def _key(code):
    if not isinstance(code, str):
        raise NetworkError('Неверный код партии')
    try:
        raw = bytes.fromhex(code.strip())
    except ValueError as exc:
        raise NetworkError('Код партии: 32 шестнадцатеричных символа') from exc
    if len(raw) != 16:
        raise NetworkError('Код партии: 32 шестнадцатеричных символа')
    return raw


def signature(key, obj):
    return hmac.new(key, dumps(obj), hashlib.sha256).hexdigest()


class Channel:
    def __init__(self, sock, key):
        self.sock, self.key = sock, key
        self.tx = self.rx = 0

    def send(self, body):
        obj = {'seq': self.tx, 'body': body}
        send_raw(self.sock, {**obj, 'mac': signature(self.key, obj)})
        self.tx += 1

    def receive(self):
        obj = recv_raw(self.sock)
        if set(obj) != {'seq', 'body', 'mac'} or type(obj['seq']) is not int or obj['seq'] != self.rx:
            raise NetworkError('Неверная последовательность пакетов')
        if not isinstance(obj['mac'], str) or not isinstance(obj['body'], dict):
            raise NetworkError('Неверный сетевой пакет')
        signed = {'seq': obj['seq'], 'body': obj['body']}
        if not hmac.compare_digest(obj['mac'], signature(self.key, signed)):
            raise NetworkError('Пакет не прошёл проверку подлинности')
        self.rx += 1
        return obj['body']


def host_handshake(sock, code, rules):
    secret = _key(code)
    hello = {'protocol': PROTOCOL, 'game': __version__, 'rules': rules, 'nonce': secrets.token_hex(16)}
    send_raw(sock, hello)
    auth = recv_raw(sock)
    if set(auth) != {'nonce', 'candidate', 'proof'} or not isinstance(auth['nonce'], str) or len(auth['nonce']) != 32:
        raise NetworkError('Неверный запрос подключения')
    challenge = {'hello': hello, 'nonce': auth['nonce'], 'candidate': auth['candidate']}
    expected = signature(secret, {'role': 'guest', **challenge})
    if not isinstance(auth['proof'], str) or not hmac.compare_digest(auth['proof'], expected):
        raise NetworkError('Неверный код партии')
    send_raw(sock, {'proof': signature(secret, {'role': 'host', **challenge})})
    session_key = hmac.new(secret, dumps(challenge), hashlib.sha256).digest()
    return Channel(sock, session_key), auth['candidate']


def guest_handshake(sock, code, rules, candidate):
    secret = _key(code)
    hello = recv_raw(sock)
    if (hello.get('protocol') != PROTOCOL or hello.get('game') != __version__ or hello.get('rules') != rules):
        raise NetworkError('Версии игры или данные отличаются. Установите одинаковую сборку.')
    if not isinstance(hello.get('nonce'), str) or len(hello['nonce']) != 32:
        raise NetworkError('Неверный ответ создателя партии')
    challenge = {'hello': hello, 'nonce': secrets.token_hex(16), 'candidate': candidate}
    send_raw(sock, {'nonce': challenge['nonce'], 'candidate': candidate,
                    'proof': signature(secret, {'role': 'guest', **challenge})})
    auth = recv_raw(sock)
    expected = signature(secret, {'role': 'host', **challenge})
    if not isinstance(auth.get('proof'), str) or not hmac.compare_digest(auth['proof'], expected):
        raise NetworkError('Создатель партии не прошёл проверку кода')
    return Channel(sock, hmac.new(secret, dumps(challenge), hashlib.sha256).digest())


class Link:
    def __init__(self):
        self.events = queue.Queue(maxsize=64)
        self.outbox = queue.Queue(maxsize=32)
        self.stopped = threading.Event()
        self.sock = self.listener = None
        self.channel = None
        self.is_host = False

    def host(self, code, rules, port=DEFAULT_PORT, bind='0.0.0.0'):
        _key(code)
        self.is_host = True
        self._thread(self._host, code, rules, int(port), bind)

    def join(self, address, code, rules, candidate, port=DEFAULT_PORT):
        _key(code)
        self._thread(self._join, address, code, rules, candidate, int(port))

    def _thread(self, fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _event(self, body):
        try:
            self.events.put(body, timeout=1)
        except queue.Full as exc:
            raise NetworkError('Очередь сетевых сообщений переполнена') from exc

    def _failure(self, exc):
        if not self.stopped.is_set():
            try:
                self.events.put_nowait({'type': 'disconnected', 'reason': str(exc)})
            except queue.Full:
                pass
            self.close()

    def _host(self, code, rules, port, bind):
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener = listener
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((bind, port))
            listener.listen(2)
            listener.settimeout(1)
            self._event({'type': 'listening', 'port': listener.getsockname()[1]})
            while not self.stopped.is_set():
                try:
                    conn, _ = listener.accept()
                except socket.timeout:
                    continue
                self.sock = conn
                conn.settimeout(15)
                try:
                    channel, cand = host_handshake(conn, code, rules)
                except (NetworkError, OSError, ValueError) as exc:
                    conn.close()
                    self.sock = None
                    self._event({'type': 'rejected', 'reason': str(exc)})
                    continue
                if self.stopped.is_set():
                    conn.close()
                    return
                listener.close()
                self.listener = None
                self._connected(channel, cand)
                return
        except (OSError, NetworkError, ValueError) as exc:
            self._failure(exc)

    def _join(self, address, code, rules, candidate, port):
        try:
            conn = socket.create_connection((address, port), timeout=15)
            self.sock = conn
            channel = guest_handshake(conn, code, rules, candidate)
            if self.stopped.is_set():
                conn.close()
                return
            self._connected(channel, None)
        except (OSError, NetworkError, ValueError) as exc:
            self._failure(exc)

    def _connected(self, channel, candidate):
        self.channel = channel
        # Read timeout detects stalled peers; writer heartbeat keeps idle games alive.
        channel.sock.settimeout(45)
        self._event({'type': 'connected', 'candidate': candidate})
        self._thread(self._writer)
        try:
            while not self.stopped.is_set():
                body = channel.receive()
                if body.get('type') != 'ping':
                    self._event(body)
        except (OSError, NetworkError, ValueError, RecursionError) as exc:
            self._failure(exc)

    def _writer(self):
        try:
            while not self.stopped.is_set():
                try:
                    body = self.outbox.get(timeout=10)
                except queue.Empty:
                    body = {'type': 'ping'}
                if self.stopped.is_set():
                    return
                self.channel.send(body)
        except (OSError, NetworkError, ValueError) as exc:
            self._failure(exc)

    def send(self, body):
        if self.channel is None or self.stopped.is_set():
            raise NetworkError('Нет соединения с другим игроком')
        try:
            self.outbox.put_nowait(body)
        except queue.Full as exc:
            raise NetworkError('Другой игрок не принимает сообщения') from exc

    def close(self):
        self.stopped.set()
        for sock in (self.sock, self.listener):
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
