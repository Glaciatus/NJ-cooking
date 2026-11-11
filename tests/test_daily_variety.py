import copy
import unittest
from core import Recipe,Ingredient,plan,validate_day_variety,recipe_key
from nutrition import DEFAULT_TARGETS,scale_macro_targets
from constrained_search import anchored_days

class DailyVarietyTests(unittest.TestCase):
    def recipes(self):
        return [Recipe(f'Блюдо {n}',1,600,[Ingredient('Рис',100,'г')],protein=25,fat=20,carbs=90) for n in range(4)]

    def test_no_repetition_in_any_generation_mode_including_preview(self):
        recipes=self.recipes()
        for mode in ('daily','weekly'):
            for control in (False,True):
                for preview in (False,True):
                    with self.subTest(mode=mode,control=control,preview=preview):
                        week=plan(recipes,target=1800,tolerance=0,macro_targets={'protein':75,'fat':60,'carbs':270},macro_tolerance=0,
                                  nutrition_mode=mode,require_nutrition=control,allow_nutrition_deviations=preview,
                                  required_ids=[recipe_key(recipes[0])],seed=2)
                        validate_day_variety(week)
                        self.assertTrue(any(recipes[0] in day for day in week))
                        self.assertEqual(sum(len(d) for d in week),21)

    def test_copies_with_same_normalized_name_do_not_count_as_different_dishes(self):
        recipes=self.recipes()[:2]
        duplicate=copy.deepcopy(recipes[0]);duplicate.uid='copy';duplicate.database_id='personal';duplicate.name='БЛЮДО 0'
        with self.assertRaisesRegex(ValueError,'три разных блюда'):plan(recipes+[duplicate],require_nutrition=False)

    def test_anchored_recovery_cannot_bypass_variety(self):
        recipes=self.recipes()[:3]
        values=[dict(kcal=600,protein=25,fat=20,carbs=90)]*3
        days,_,_=anchored_days(0,[[0,1,2]]*3,values,recipes,DEFAULT_TARGETS,dict.fromkeys(DEFAULT_TARGETS,9999),1,False,{})
        self.assertTrue(days)
        for day in days:self.assertEqual(len(set(day)),3)

    def test_macros_match_calories_and_preserve_energy_shares(self):
        values=scale_macro_targets(1600,{'protein':100,'fat':40,'carbs':160})
        self.assertAlmostEqual(4*values['protein']+9*values['fat']+4*values['carbs'],1600,delta=1)
        self.assertAlmostEqual(values['protein']/values['fat'],2.5,delta=.01)
        self.assertAlmostEqual(values['carbs']/values['protein'],1.6,delta=.01)
        self.assertEqual(scale_macro_targets(1600,{}),scale_macro_targets(1600,DEFAULT_TARGETS))
