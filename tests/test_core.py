import unittest
import tempfile
import zipfile
from pathlib import Path
from core import Ingredient, Recipe, totals, plan, word_text
from nutrition import recipe_nutrition

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.r = Recipe('Каша', 4, 600, [Ingredient('Рис', 0.4, 'кг')])

    def test_scaling_and_units(self):
        other = Recipe('Рис', 2, 500, [Ingredient('рис', 100, 'г')])
        self.assertEqual(totals([(self.r, 2), (other, 2)]), {('рис', 'г'): 300})

    def test_week_calories_and_wishes(self):
        week = plan([self.r], 3, 1, 1800, 0, wanted=['рис'], seed=1, macro_targets={k:recipe_nutrition(self.r)[0][k]*3 for k in ('protein','fat','carbs')}, macro_tolerance=0)
        self.assertEqual(len(week), 7)
        self.assertTrue(all(sum(r.kcal for r in day) == 1800 for day in week))
        self.assertAlmostEqual(totals([(r, 3) for day in week for r in day])[('рис', 'г')], 6300)

    def test_excluded_and_impossible(self):
        with self.assertRaises(ValueError):
            plan([self.r], 2, 1, 1800, 0, excluded=['рис'])
        with self.assertRaises(ValueError):
            plan([self.r], 2, 1, 1000, 0)
        with self.assertRaises(ValueError):
            plan([self.r], 2, 1, 1800, 0, wanted=['морковь'])

    def test_word_multiple_paragraphs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recipes.docx'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Суп</w:t></w:r></w:p><w:p><w:r><w:t>Рис</w:t></w:r></w:p></w:body></w:document>')
            self.assertEqual(word_text(path), 'Суп\nРис')

if __name__ == '__main__':
    unittest.main()
