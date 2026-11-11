import unittest
from core import Ingredient, Recipe, readiness, validate_recipe, plan
from nutrition import number, recipe_nutrition, nutrition_totals, DEFAULT_TARGETS, ingredient_mass
from estimation import servings_info
from examples import example_recipes

class NutritionTests(unittest.TestCase):
    def test_missing_calories_estimated_and_scaled(self):
        r = Recipe('Рис', 4, None, [Ingredient('Рис', .4, 'кг')])
        values, estimated = recipe_nutrition(r)
        self.assertEqual(values['kcal'], 365)
        self.assertEqual(values['carbs'], 80)
        self.assertEqual(estimated, {'kcal', 'protein', 'fat', 'carbs'})
        self.assertEqual(nutrition_totals([(r, 2)])['kcal'], 730)
        self.assertFalse(readiness(r))

    def test_unknown_does_not_become_zero(self):
        r = Recipe('Неизвестное блюдо', None, None, [Ingredient('Фирменный соус', 100, 'г')])
        validate_recipe(r)  # Drafts are valid storage objects.
        self.assertTrue(all(v is None for v in recipe_nutrition(r)[0].values()))
        self.assertTrue(readiness(r))
        with self.assertRaisesRegex(ValueError, 'Нет готовых'):
            plan([r])

    def test_manual_macros_energy_formula_and_zero(self):
        r = Recipe('Блюдо', 1, None, [Ingredient('Соус', 100, 'г')], protein=10, fat=0, carbs=20)
        self.assertEqual(recipe_nutrition(r)[0]['kcal'], 120)
        self.assertEqual(recipe_nutrition(r)[0]['fat'], 0)
        self.assertFalse(readiness(r))

    def test_missing_servings_and_empty_fields(self):
        self.assertIsNone(number('', 'Ккал'))
        self.assertEqual(number('', 'Ккал', default=2000), 2000)
        r = Recipe('Каша', None, None, [Ingredient('Рис', 100, 'г')])
        validate_recipe(r)
        self.assertIsNotNone(servings_info(r).servings)
        self.assertTrue(servings_info(r).estimated)

    def test_invalid_numbers(self):
        for value in ('nan', 'inf', '-2', 'abc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value, 'Калории')
        with self.assertRaises(ValueError):
            number('1.5', 'Люди', integer=True)
        with self.assertRaises(ValueError):
            number('0', 'Порции', allow_zero=False)
        self.assertEqual(number('2,5', 'Порции'), 2.5)

    def test_units_do_not_invent_weight(self):
        r = Recipe('Масло', 1, None, [Ingredient('Оливковое масло', 1, 'ст. л.')])
        self.assertGreater(recipe_nutrition(r)[0]['kcal'],0)
        self.assertAlmostEqual(ingredient_mass(r.ingredients[0]),13.5)
        r.ingredients[0] = Ingredient('Яйцо', 2, 'шт')
        self.assertEqual(recipe_nutrition(r)[0]['kcal'], 143)
        r.ingredients[0] = Ingredient('Продукт', 2, 'шт', [100, 5, 0, 20], 50)
        self.assertEqual(recipe_nutrition(r)[0]['kcal'], 100)

    def test_defaults_all_four_bounds_exclusions_and_wishes(self):
        week = plan(example_recipes(), target='', tolerance='', wanted=['рис'], excluded=['лосось'], seed=3)
        self.assertEqual(len(week), 7)
        self.assertTrue(any('Рис' == i.name for day in week for r in day for i in r.ingredients))
        for day in week:
            self.assertFalse(any('Лосось' == i.name for r in day for i in r.ingredients))
            values = nutrition_totals([(r, 1) for r in day])
            self.assertLessEqual(abs(values['kcal']-2000), 200)
            for key in ('protein', 'fat', 'carbs'):
                self.assertLessEqual(abs(values[key]-DEFAULT_TARGETS[key]), DEFAULT_TARGETS[key]*.2)

    def test_custom_goals_and_portion_scaling(self):
        r = Recipe('Блюдо', 4, 500, [Ingredient('Рис', 400, 'г')], protein=20, fat=15, carbs=70)
        week = plan([r], portions=2, target=3000, tolerance=0,
                    macro_targets={'protein':120, 'fat':90, 'carbs':420}, macro_tolerance=0, seed=2)
        self.assertEqual(nutrition_totals([(r, 2) for r in week[0]])['protein'], 120)

    def test_import_does_not_require_confirmation(self):
        r = example_recipes()[0]
        r.reviewed = False
        self.assertFalse(readiness(r))

    def test_macro_constraint_does_not_silently_relax(self):
        r = Recipe('Рис', 1, 666, [Ingredient('Рис', 100, 'г')], protein=1, fat=1, carbs=150)
        with self.assertRaisesRegex(ValueError, 'Ближайший'):
            plan([r])
