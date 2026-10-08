import unittest
from unittest.mock import patch
from gorod import engine as E, graphics as G


class GraphicsTest(unittest.TestCase):
    def test_config_paths(self):
        c = G.config()
        self.assertEqual(len(c['portrait_names']), 4)
        self.assertTrue((E.DATA_DIR/c['city']).is_file())

    @unittest.skipUnless(G.AVAILABLE, 'Pillow optional for solo engine')
    def test_art(self):
        im = G.city(640, 480)
        self.assertLessEqual(im.width, 640)
        self.assertLessEqual(im.height, 480)
        for i in range(4):
            self.assertEqual(G.portrait(i, 90).size, (90, 90))

    @unittest.skipUnless(G.AVAILABLE, 'Pillow optional for solo engine')
    def test_newspaper_wrap_no_overflow(self):
        f = G.font(20)
        lines = G.wrapped('Оченьдлинноеимя'*80, f, 420)
        self.assertTrue(all(f.getlength(line) <= 420 for line in lines))
        articles = [{'paper_name': 'Голос улицы', 'headline': 'Новый кандидат встречается с городом',
                     'lead': 'Пенсионеры и рабочие обсуждают тарифы. '*30}]
        small = G.newspaper(articles, 3, 480)
        large = G.newspaper(articles, 3, 900)
        self.assertEqual(small.width, 480)
        self.assertGreater(small.height, large.height)
        self.assertEqual(G.newspaper([], 0).mode, 'RGB')

    def test_visible_no_pillow_error(self):
        with patch.object(G, 'AVAILABLE', False):
            with self.assertRaises(E.DataError):
                G.newspaper([], 0)

    def test_palette_invalid(self):
        bad = G.config()
        bad['palette']['ink'] = 'not-a-color'
        with patch.object(G, 'load_json', return_value=bad):
            with self.assertRaises(E.DataError):
                G.config()


if __name__ == '__main__':
    unittest.main()
