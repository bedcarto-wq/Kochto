import copy
import json
import socket
import struct
import tempfile
import threading
import time
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from gorod import engine as E
from gorod.multiplayer import Match, candidate, fingerprint
from gorod.p2p import (Channel, Link, NetworkError, guest_handshake, host_handshake,
                       new_code, send_raw, signature, MAX_PACKET)

SKILLS = {'charm': 30, 'eloquence': 30, 'cunning': 30}


class MatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = E.load_data()

    def setUp(self):
        self.m = Match(self.data, [candidate('Анна', 'f', SKILLS), candidate('Борис', 'm', SKILLS)], seed=81)

    def act(self, i, card, text=''):
        return self.m.command(i, self.m.revision, 'action', {'card': asdict(card), 'text': text})

    def ready(self, i):
        return self.m.command(i, self.m.revision, 'ready')

    def assert_sync(self):
        a, b = self.m.states
        self.assertEqual(a.policies, b.policies)
        self.assertEqual(a.council, b.council)
        self.assertEqual(a.week, b.week)
        for gid in a.groups:
            self.assertEqual(a.groups[gid].support_player, b.groups[gid].support_rival)
            self.assertEqual(a.groups[gid].support_rival, b.groups[gid].support_player)
            self.assertEqual(a.groups[gid].rival_trust, b.groups[gid].trust)

    def test_equal_start_and_alternate(self):
        self.assert_sync()
        a = E.election(self.m.states[0], self.m.scoped_data(0), None)
        b = E.election(self.m.states[1], self.m.scoped_data(1), None)
        self.assertEqual(a['player'], a['rival'])
        self.assertEqual(a['player'], b['rival'])
        self.ready(0)
        self.assertEqual(self.m.states[0].week, 1)
        self.ready(1)
        self.assertEqual(self.m.states[0].week, 2)
        self.assertEqual(self.m.turn, 1)
        self.assert_sync()
        self.ready(1)
        self.ready(0)
        self.assertEqual(self.m.turn, 0)
        self.assert_sync()

    def test_private_fields_and_zero_sum(self):
        g = next(iter(self.data['groups']))
        before = copy.deepcopy(self.m.states)
        self.act(0, E.Card('meeting', group=g), 'Встретиться с рабочими')
        self.assertEqual(before[1].money, self.m.states[1].money)
        self.assertEqual(before[1].actions_left, self.m.states[1].actions_left)
        self.assertEqual(self.m.states[0].actions_left, 2)
        self.assertEqual(len(self.m.states[0].learned), 1)
        self.assertEqual(len(self.m.states[1].learned), 0)
        self.assert_sync()
        self.ready(0)
        self.act(1, E.Card('meeting', group=g))
        self.assert_sync()

    def test_wrong_turn_and_stale_are_atomic(self):
        before = self.m.snapshot()
        with self.assertRaises(E.RuleError):
            self.m.command(1, 0, 'ready')
        self.assertEqual(self.m.snapshot(), before)
        self.ready(0)
        before = self.m.snapshot()
        with self.assertRaises(E.RuleError):
            self.m.command(1, 0, 'ready')
        self.assertEqual(self.m.snapshot(), before)

    def test_invalid_card_is_atomic(self):
        before = self.m.snapshot()
        with self.assertRaises(E.RuleError):
            self.act(0, E.Card('meeting', group='unknown'))
        self.assertEqual(self.m.snapshot(), before)
        with self.assertRaises(E.RuleError):
            self.act(0, E.Card('bad'))
        self.assertEqual(self.m.snapshot(), before)
        raw = asdict(E.Card('meeting', group=next(iter(self.data['groups']))))
        raw['side'] = True
        with self.assertRaises(E.RuleError):
            self.m.command(0, 0, 'action', {'card': raw, 'text': ''})
        self.assertEqual(self.m.snapshot(), before)

    def test_no_ai_moves(self):
        with patch.object(E, '_rival_turn', side_effect=AssertionError('AI in PvP')):
            for _ in range(4):
                first = self.m.turn
                self.ready(first)
                self.ready(1-first)
        self.assertFalse(any(f.actor == 'rival' for s in self.m.states for f in s.facts))

    def test_shared_policy_fulfills_both_promises(self):
        pid = next(iter(self.data['proposals']))
        pleased = [g for g in self.data['groups'] if E.stance(self.data, g, pid) > 0]
        for s in self.m.states:
            s.promises.append(E.Promise('p1', pid, 1, 1, 2, pleased))
        self.m.states[0].policies[pid] = 1
        self.m._sync(0)
        self.assertTrue(all(s.promises[0].status == 'kept' for s in self.m.states))
        self.assert_sync()

    def test_election_shared_and_projection_consistent(self):
        for _ in range(12):
            first = self.m.turn
            self.ready(first)
            self.ready(1-first)
        a, b = self.m.states
        self.assertEqual(a.week, 13)
        ea, eb = a.elections[-1], b.elections[-1]
        self.assertEqual(ea['player'], eb['rival'])
        self.assertEqual(ea['rival'], eb['player'])
        self.assertEqual(ea['council'], eb['council'])
        self.assertEqual(sum(a.council.values()), 9)
        fa = E.election(a, self.m.scoped_data(0), None)
        fb = E.election(b, self.m.scoped_data(1), None)
        self.assertEqual(fa['council'], fb['council'])
        self.assert_sync()

    def test_death_ends_whole_match(self):
        def death(s, data, rng):
            s.dead = True
            s.death_week = s.week
        with patch.object(E, '_threat_phase', side_effect=death):
            self.ready(0)
            self.ready(1)
        self.assertTrue(self.m.ended)
        self.assertTrue(all(s.actions_left == 0 for s in self.m.states))
        with self.assertRaises(E.RuleError):
            self.ready(self.m.turn)

    def test_save_restore_and_checksum(self):
        self.ready(0)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'game.p2p.json'
            self.m.save(p)
            loaded = Match.load(self.data, p)
            self.assertEqual(loaded.snapshot(), self.m.snapshot())
            loaded.command(1, loaded.revision, 'ready')
            obj = json.loads(p.read_text())
            obj['match']['revision'] += 1
            p.write_text(json.dumps(obj))
            with self.assertRaises(E.DataError):
                Match.load(self.data, p)

    def test_restore_rejects_bad_shape(self):
        for key, value in [('ready', [False]), ('reports', []), ('journal', [3]), ('turn', True)]:
            obj = self.m.snapshot()
            obj[key] = value
            with self.assertRaises(E.DataError):
                Match.restore(self.data, obj)

    def test_rules_mismatch(self):
        obj = self.m.snapshot()
        obj['rules'] = 'bad'
        with self.assertRaises(E.DataError):
            Match.restore(self.data, obj)


class WireTest(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair()
        self.a.settimeout(2)
        self.b.settimeout(2)
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)
        self.key = b'k'*32

    def test_channel(self):
        a, b = Channel(self.a, self.key), Channel(self.b, self.key)
        a.send({'type': 'test', 'text': 'Город'})
        self.assertEqual(b.receive()['text'], 'Город')
        b.send({'type': 'response'})
        self.assertEqual(a.receive()['type'], 'response')

    def test_tamper(self):
        signed = {'seq': 0, 'body': {'type': 'ready'}}
        send_raw(self.a, {**signed, 'mac': '0'*64})
        with self.assertRaises(NetworkError):
            Channel(self.b, self.key).receive()

    def test_replay(self):
        signed = {'seq': 0, 'body': {'type': 'ready'}}
        packet = {**signed, 'mac': signature(self.key, signed)}
        send_raw(self.a, packet)
        send_raw(self.a, packet)
        channel = Channel(self.b, self.key)
        channel.receive()
        with self.assertRaises(NetworkError):
            channel.receive()

    def test_oversize_before_body(self):
        self.a.sendall(struct.pack('!I', MAX_PACKET+1))
        with self.assertRaises(NetworkError):
            Channel(self.b, self.key).receive()

    def handshake(self, wrong=False):
        code = new_code()
        result = []
        def host():
            try:
                result.append(host_handshake(self.a, code, 'rules'))
            except Exception as exc:
                result.append(exc)
                self.a.close()
        t = threading.Thread(target=host)
        t.start()
        if wrong:
            with self.assertRaises(NetworkError):
                guest_handshake(self.b, new_code(), 'rules', {'name': 'Борис'})
        else:
            guest = guest_handshake(self.b, code, 'rules', {'name': 'Борис'})
            t.join(3)
            channel, cand = result[0]
            self.assertEqual(cand['name'], 'Борис')
            guest.send({'type': 'hello'})
            self.assertEqual(channel.receive()['type'], 'hello')
        t.join(3)
        self.assertFalse(t.is_alive())
        return result

    def test_handshake(self):
        self.handshake()

    def test_wrong_code(self):
        self.assertIsInstance(self.handshake(True)[0], NetworkError)

    def test_real_tcp_links_and_disconnect(self):
        data = E.load_data()
        rules, code = fingerprint(data), new_code()
        host, guest = Link(), Link()
        self.addCleanup(host.close)
        self.addCleanup(guest.close)
        host.host(code, rules, port=0, bind='127.0.0.1')
        listening = host.events.get(timeout=3)
        guest.join('127.0.0.1', code, rules, candidate('Друг', 'm', SKILLS), port=listening['port'])
        self.assertEqual(host.events.get(timeout=3)['type'], 'connected')
        self.assertEqual(guest.events.get(timeout=3)['type'], 'connected')
        host.send({'type': 'state', 'n': 12})
        self.assertEqual(guest.events.get(timeout=3)['n'], 12)
        guest.close()
        self.assertEqual(host.events.get(timeout=3)['type'], 'disconnected')


if __name__ == '__main__':
    unittest.main()
