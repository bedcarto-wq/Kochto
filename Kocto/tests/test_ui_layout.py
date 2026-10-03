"""Panel layout logic + optional real-Tk smoke test."""
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui_layout as L


class LayoutLogicTests(unittest.TestCase):
    def test_normalize_repairs_garbage(self):
        lay = L.normalize({'order': ['right', 'bogus', 'right'], 'hidden': ['center', 'left', 'x'], 'sizes': {'left': 10, 'x': 5, 'right': -1}})
        self.assertEqual(lay['order'], ['right', 'left', 'center'])
        self.assertEqual(lay['hidden'], ['left'])  # center can never be hidden
        self.assertEqual(lay['sizes'], {'left': L.MIN_WIDTH})
        self.assertEqual(L.normalize(None), L.default_layout())

    def test_move_and_bounds(self):
        lay = L.move(L.default_layout(), 'right', -1)
        self.assertEqual(lay['order'], ['left', 'right', 'center'])
        lay = L.move(lay, 'right', -5)
        self.assertEqual(lay['order'], ['right', 'left', 'center'])
        self.assertEqual(L.move(lay, 'center', 9)['order'][-1], 'center')

    def test_toggle_keeps_center(self):
        lay = L.toggle(L.default_layout(), 'left')
        self.assertEqual(L.visible(lay), ['center', 'right'])
        self.assertEqual(L.visible(L.toggle(lay, 'center')), ['center', 'right'])
        self.assertEqual(L.visible(L.toggle(lay, 'left')), ['left', 'center', 'right'])

    def test_save_load_roundtrip_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sub' / 'layout.json'
            lay = L.toggle(L.move(L.default_layout(), 'left', 2), 'right')
            self.assertTrue(L.save(path, lay))
            self.assertEqual(L.load(path), L.normalize(lay))
            path.write_text('{oops', encoding='utf-8')
            self.assertEqual(L.load(path), L.default_layout())
            self.assertEqual(L.load(Path(tmp) / 'missing.json'), L.default_layout())

    def test_install_uninstall_restores_class(self):
        class Fake:
            def _build(self, titles):
                return 'old'

            def _close(self):
                return 'closed'
        module = types.SimpleNamespace(TkinterUI=Fake)
        old_build = Fake._build
        L.install(module, '/tmp/x.json')
        self.assertIsNot(Fake._build, old_build)
        L.uninstall(module)
        self.assertIs(Fake._build, old_build)
        self.assertFalse(hasattr(Fake, '_layout_path'))


class TkSmokeTests(unittest.TestCase):
    def test_real_window_buttons_stay_and_panels_move(self):
        try:
            import tkinter as tk
            from tkinter import ttk
            root = tk.Tk()
            root.withdraw()
        except Exception as exc:  # no display / no tkinter
            self.skipTest(f'Tk unavailable: {exc}')

        class FakeUI:
            def __init__(self):
                self.tk, self.ttk, self.root = tk, ttk, root
                self.on_command = lambda c: None
                self.closed = False

            def _build(self, titles):
                pass

            def _submit(self):
                pass

            def _history_step(self, step):
                return 'break'

            def _close(self):
                self.closed = True
        module = types.SimpleNamespace(TkinterUI=FakeUI)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'layout.json'
            L.install(module, path)
            try:
                ui = FakeUI()
                ui._build([('a1', 'A1'), ('a2', 'A2')])
                root.update_idletasks()
                self.assertEqual(len(ui._paned.panes()), 3)
                for attr in ('header', 'left', 'center', 'right', 'entry', '_history', '_hist_pos'):
                    self.assertTrue(hasattr(ui, attr), attr)
                L._change(ui, L.toggle(ui._layout, 'left'))
                self.assertEqual(len(ui._paned.panes()), 2)
                L._change(ui, L.move(ui._layout, 'right', -2))
                self.assertEqual(ui._layout['order'][0], 'right')
                ui._close()
                self.assertTrue(ui.closed)
                self.assertEqual(L.load(path)['hidden'], ['left'])
            finally:
                L.uninstall(module)
                root.destroy()


if __name__ == '__main__':
    unittest.main()
