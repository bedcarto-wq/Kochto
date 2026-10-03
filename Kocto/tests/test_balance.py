"""Balance guard rails from the automated simulation (fake engine, short run)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import balance_sim


class BalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = balance_sim.simulate(weeks=24, seeds=3)

    def test_passive_loses_to_honest(self):
        self.assertGreater(self.table['honest']['mood'], self.table['passive']['mood'] + 10)

    def test_chances_stay_in_corridor(self):
        for name in ('honest', 'dirty'):
            row = self.table[name]
            self.assertGreaterEqual(row['chance_min'], 15, name)
            self.assertLessEqual(row['chance_max'], 90, name)

    def test_safe_actions_rarely_catastrophic(self):
        self.assertLessEqual(self.table['honest']['catastrophe_rate'], 0.02)

    def test_dirty_leaves_evidence(self):
        self.assertGreater(self.table['dirty']['evidence'], self.table['honest']['evidence'])


if __name__ == '__main__':
    unittest.main()
