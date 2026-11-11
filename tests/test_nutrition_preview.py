import unittest
from core import Recipe,Ingredient,plan,recipe_key,NutritionSearchFailure
from reports import week_issues

class NutritionPreviewTests(unittest.TestCase):
    def recipe(self,name,fat=10,db='personal'):
        return Recipe(name,1,500,[Ingredient('Рис',100,'г')],protein=25,fat=fat,carbs=80,database_id=db)

    def test_preview_keeps_complete_nutrition_required_and_exact_database_quota(self):
        lasagna=self.recipe('Лазанья',73)
        side=self.recipe('Гарнир')
        unknown=self.recipe('Неизвестное КБЖУ');unknown.fat=None;unknown.ingredients=[Ingredient('Неизвестный ингредиент XYZ',100,'г')]
        args=dict(target=1600,tolerance=200,macro_targets={'protein':75,'fat':30,'carbs':275},
                  required_ids=[recipe_key(lasagna)],database_limits={'personal':21},seed=1)
        with self.assertRaises(NutritionSearchFailure):plan([lasagna,side,unknown],**args)
        week=plan([lasagna,side,unknown],**args,allow_nutrition_deviations=True)
        self.assertEqual(sum(len(d) for d in week),21)
        self.assertTrue(any(lasagna in d for d in week))
        self.assertFalse(any(unknown in d for d in week))
        self.assertTrue(all(r.database_id=='personal' for d in week for r in d))
        issues=week_issues(week,1,{'kcal':1600,'protein':75,'fat':30,'carbs':275},200,.2)
        self.assertTrue(any('Жиры — 93.00 г' in x and 'на 57.00 г' in x for x in issues))

    def test_preview_does_not_override_exclusions_or_invalid_database_quotas(self):
        r=self.recipe('Рецепт')
        with self.assertRaises(ValueError):plan([r],required_ids=[recipe_key(r)],excluded=['рис'],allow_nutrition_deviations=True)
        with self.assertRaises(ValueError):plan([r],database_limits={'personal':20},allow_nutrition_deviations=True)

    def test_differences_are_from_bounds_and_include_underflow(self):
        r=self.recipe('Рецепт',fat=12.1)
        issues=week_issues([(r,r,r)]*7,1,{'kcal':1600,'protein':100,'fat':30,'carbs':300},200,.2)
        self.assertIn('День 1: Жиры — 36.30 г; допустимо 24.00–36.00 г; выше максимума на 0.30 г.',issues)
        self.assertTrue(any('Белки — 75.00 г' in x and 'ниже минимума на 5.00 г' in x for x in issues))
        self.assertFalse(any('Калории' in x for x in issues))
