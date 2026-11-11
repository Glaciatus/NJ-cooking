"""Regression for manually entered porridges rejected for unknown ingredient amounts."""
import unittest
from core import Recipe,Ingredient,plan,readiness,recipe_key
from nutrition import DEFAULT_TARGETS,nutrition_totals
from reports import week_report

class RequiredRegressionTests(unittest.TestCase):
    def porridge(self,name):
        return Recipe(name,4,562,[Ingredient('Крупа',300,'г'),Ingredient('Соль',None,'')],
                      protein=15,fat=14,carbs=95,tags=['Каша'])

    def test_two_required_porridges_with_manual_nutrition_and_unknown_quantities(self):
        apricot=self.porridge('Абрикосовая каша')
        corn=self.porridge('Кукурузная каша')
        other=Recipe('Другое блюдо',1,650,[Ingredient('Курица',200,'г')],protein=30,fat=22,carbs=75,tags=['Мясное блюдо'])
        self.assertFalse(readiness(apricot,True))
        other2=Recipe.from_dict({**other.to_dict(),"uid":"other2","name":"Второе мясное"})
        week=plan([apricot,corn,other,other2],required_ids=[recipe_key(apricot),recipe_key(corn)],
                  desired_tags=['Мясное блюдо'],require_nutrition=True,seed=7)
        used={recipe_key(r) for day in week for r in day}
        self.assertTrue({recipe_key(apricot),recipe_key(corn)}<=used)
        for day in week:
            values=nutrition_totals([(r,1) for r in day])
            self.assertLessEqual(abs(values['kcal']-2000),200)
            for key in ('protein','fat','carbs'):
                self.assertLessEqual(abs(values[key]-DEFAULT_TARGETS[key]),DEFAULT_TARGETS[key]*.2)
        report=week_report(week,2,1,DEFAULT_TARGETS,200,.2,True)
        self.assertIn('НЕ ВКЛЮЧЕНО В ЧИСЛОВУЮ СУММУ',report)
        self.assertIn('Соль',report)

    def test_required_recipe_still_respects_excluded_products_with_specific_reason(self):
        r=self.porridge('Кукурузная каша')
        with self.assertRaisesRegex(ValueError,'содержит исключённые продукты: крупа') as error:
            plan([r],required_ids=[recipe_key(r)],excluded=['крупа'])
        self.assertNotIn('количество и единицы',str(error.exception))
        self.assertNotIn('теги, исключения',str(error.exception))

    def test_missing_nutrition_still_reported_specifically(self):
        r=Recipe('Без КБЖУ',4,None,[Ingredient('Неизвестный продукт',100,'г')])
        with self.assertRaisesRegex(ValueError,'дополните КБЖУ: калории, белки, жиры, углеводы'):
            plan([r],required_ids=[recipe_key(r)],require_nutrition=True)

    def test_ordinary_recipes_remain_subject_to_tag_filter(self):
        r=self.porridge('Необязательная каша')
        with self.assertRaisesRegex(ValueError,'Нет готовых'):
            plan([r],desired_tags=['Суп'],require_nutrition=False)
