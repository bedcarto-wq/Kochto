import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import skills


class SkillTests(unittest.TestCase):
    def test_pool_exact_and_zero_allowed(self):
        self.assertEqual(skills.parse('90 0 0'), {'charm': 90, 'eloquence': 0, 'cunning': 0})
        for bad in ('30 30', '50 50 50', '30 30 29', '-1 61 30', 'a b c', '101 0 0'):
            with self.assertRaises(skills.SkillError):
                skills.parse(bad)

    def test_apply_and_legacy_fallback(self):
        state = NS(world={}, player=NS(charisma=5, persuasion=5, stealth=7))
        self.assertEqual(skills.value(state, 'cunning'), 42)
        skills.apply(state, {'charm': 30, 'eloquence': 60, 'cunning': 0})
        self.assertEqual(skills.value(state, 'eloquence'), 60)
        self.assertEqual((state.player.charisma, state.player.persuasion, state.player.media, state.player.stealth), (5, 10, 8, 0))
        self.assertIn('Хитрость 0', skills.describe(state))


if __name__ == '__main__':
    unittest.main()
