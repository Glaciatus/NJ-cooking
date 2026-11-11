import unittest
from core import Recipe,Ingredient,MEALS,plan,recipe_key,NutritionSearchFailure
from nutrition import nutrition_totals
from reports import week_issues,week_report


def recipe(name,kcal,protein,fat,carbs,meal,db):
    return Recipe(name,1,kcal,[Ingredient('Рис',100,'г')],protein=protein,fat=fat,carbs=carbs,meal=meal,database_id=db)

class WeeklyBalanceTests(unittest.TestCase):
    def setUp(self):
        self.low=recipe('Лёгкий завтрак',800,15,20,90,'Завтрак','personal')
        self.high=recipe('Сытный завтрак',1200,15,20,90,'Завтрак','personal')
        self.lunch=recipe('Обед',500,30,23.5,92.5,'Обед','big')
        self.dinner=recipe('Ужин',500,30,23.5,92.5,'Ужин','big')
        self.recipes=[self.low,self.high,self.lunch,self.dinner]
        self.args=dict(target=2000,tolerance=30,macro_tolerance=.02,seed=5,
                       required_ids=[recipe_key(self.high)],database_limits={'personal':7,'big':14})
        self.targets={'kcal':2000,'protein':75,'fat':67,'carbs':275}

    def test_week_compensates_days_without_loosening_weekly_bounds(self):
        with self.assertRaises(NutritionSearchFailure):plan(self.recipes,**self.args,nutrition_mode='daily')
        week=plan(self.recipes,**self.args,nutrition_mode='weekly')
        totals=nutrition_totals([(r,1) for day in week for r in day])
        self.assertLessEqual(abs(totals['kcal']/7-2000),30)
        daily=[nutrition_totals([(r,1) for r in day])['kcal'] for day in week]
        self.assertEqual(set(daily),{1800,2200})
        self.assertTrue(any(self.high in day for day in week))
        self.assertEqual(sum(r.database_id=='personal' for day in week for r in day),7)
        self.assertFalse(week_issues(week,1,self.targets,30,.02,nutrition_mode='weekly'))
        self.assertTrue(week_issues(week,1,self.targets,30,.02,nutrition_mode='daily'))
        report=week_report(week,2,1,self.targets,30,.02,nutrition_mode='weekly')
        self.assertIn('недельный баланс',report)
        self.assertIn('Дневные границы на человека',report)

    def test_21_compulsory_recipes_are_preserved_with_joint_weekly_budget(self):
        recipes=[]
        for day in range(7):
            recipes += [recipe(f'Завтрак {day}',1200 if day<3 else 800,15,20,90,'Завтрак','personal'),
                        recipe(f'Обед {day}',500,30,23.5,92.5,'Обед','big'),
                        recipe(f'Ужин {day}',500,30,23.5,92.5,'Ужин','big')]
        args={**self.args,'required_ids':[recipe_key(r) for r in recipes]}
        week=plan(recipes,**args,nutrition_mode='weekly')
        self.assertEqual({recipe_key(r) for d in week for r in d},set(args['required_ids']))
        self.assertFalse(week_issues(week,1,self.targets,30,.02,nutrition_mode='weekly'))

    def test_daily_protein_floor_blocks_compensation_by_next_day(self):
        self.low.protein=0;self.high.protein=0
        # Lunch/dinner total 60 g protein. A configured 90% floor is 67.5 g.
        with self.assertRaises(NutritionSearchFailure):
            plan(self.recipes,**self.args,nutrition_mode='weekly',protein_floor=.9)

    def test_average_outside_tolerance_is_not_accepted(self):
        with self.assertRaises(NutritionSearchFailure):
            plan([self.high,self.lunch,self.dinner],**self.args,nutrition_mode='weekly')
        week=plan([self.high,self.lunch,self.dinner],**self.args,nutrition_mode='weekly',allow_nutrition_deviations=True)
        issues=week_issues(week,1,self.targets,30,.02,nutrition_mode='weekly')
        self.assertTrue(any('Среднее за день недели' in x and '170.00 ккал' in x for x in issues))

    def test_manual_edit_warns_about_daily_guard_and_weekly_average(self):
        week=[(self.low,self.lunch,self.dinner)]*7
        self.low.kcal=100
        issues=week_issues(week,1,self.targets,30,.02,nutrition_mode='weekly')
        self.assertTrue(any(x.startswith('День 1: Калории') for x in issues))
        self.assertTrue(any(x.startswith('Среднее за день недели: Калории') for x in issues))

    def test_daily_closeness_is_preferred_when_weekly_average_is_equal(self):
        middle=recipe('Ровный завтрак',1000,15,20,90,'Завтрак','personal')
        args={**self.args,'required_ids':[],'tolerance':0}
        week=plan(self.recipes+[middle],**args,nutrition_mode='weekly')
        self.assertTrue(all(middle in d for d in week))

    def test_targets_are_per_person_with_fractional_portions(self):
        args={**self.args,'portions':.5,'target':1000,'tolerance':15,
              'macro_targets':{'protein':37.5,'fat':33.5,'carbs':137.5}}
        week=plan(self.recipes,**args,nutrition_mode='weekly',people=5)
        average=nutrition_totals([(r,.5/7) for day in week for r in day])
        self.assertLessEqual(abs(average['kcal']-1000),15)
        self.assertAlmostEqual(average['protein'],37.5)

    def test_invalid_mode_and_percentages_are_rejected(self):
        for settings in ({'nutrition_mode':'other'},{'nutrition_mode':'weekly','protein_floor':1.1}):
            with self.assertRaises(ValueError):plan(self.recipes,**settings)
