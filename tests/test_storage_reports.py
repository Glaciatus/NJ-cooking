import json
from pathlib import Path
import tempfile
import unittest
from core import Recipe, Ingredient, plan
from examples import example_recipes
from storage import load_recipes, save_recipes
from reports import week_report
from nutrition import DEFAULT_TARGETS

class StorageReportTests(unittest.TestCase):
    def test_old_library_migration_and_backup(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'recipes.json'
            old = [{'name':'Рис', 'servings':4,'kcal':400,'ingredients':[{'name':'Рис','amount':400,'unit':'г'}], 'method':'Сварить'}]
            path.write_text(json.dumps(old), encoding='utf-8')
            recipes = load_recipes(path)
            self.assertIsNone(recipes[0].protein)
            self.assertEqual(recipes[0].source_url, '')
            recipes[0].source_url = 'https://example.com/recipe'
            save_recipes(path, recipes)
            self.assertEqual(load_recipes(path)[0].source_url, 'https://example.com/recipe')
            self.assertEqual(json.loads(path.with_suffix('.json.bak').read_text(encoding='utf-8')), old)

    def test_draft_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'r.json'
            save_recipes(path, [Recipe('Неполный', None, None, [Ingredient('Соль', None, '')])])
            r=load_recipes(path)[0]
            self.assertIsNone(r.kcal)
            self.assertIsNone(r.servings)
            self.assertIsNone(r.ingredients[0].amount)

    def test_corrupted_storage_not_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'r.json'
            path.write_text('broken', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'не перезаписаны'):
                load_recipes(path)
            self.assertEqual(path.read_text(encoding='utf-8'), 'broken')

    def test_report_has_macros_source_and_week_family_totals(self):
        recipes=example_recipes()
        for r in recipes:
            r.source_url='https://example.com/recipe'
        week=plan(recipes, seed=1)
        report=week_report(week, 2, 1, DEFAULT_TARGETS, 200, .2)
        for text in ('Б ', 'Ж ', 'У ', 'ИТОГО ЗА НЕДЕЛЮ', 'ПРОДУКТЫ ЗА ДЕНЬ', 'СПИСОК ПОКУПОК', 'https://example.com/recipe', 'Среднее за день на человека'):
            self.assertIn(text, report)
