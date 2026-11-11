import logging
import random
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from core import Recipe,Ingredient,plan,recipe_key
from diagnostics import APP_VERSION,configure_logging,close_logging,log_plan

class FirstChoiceRandom(random.Random):
    def choice(self,sequence):return sequence[0]


def food(name,kcal,p,f,c,meal):
    return Recipe(name,1,kcal,[Ingredient('Рис',100,'г')],protein=p,fat=f,carbs=c,meal=meal)

class AnchoredSearchTests(unittest.TestCase):
    def test_recovers_valid_required_day_missed_by_sampler(self):
        normal=food('Обычный завтрак',600,25,20,90,'Завтрак')
        corn=food('Кукурузная каша',500,15,14,95,'Завтрак')
        lunches=[food('Обычный обед',700,25,20,90,'Обед')]
        dinners=[food('Обычный ужин',700,25,27,95,'Ужин')]
        lunches += [food(f'Другой обед {n}',111,1,1,1,'Обед') for n in range(398)]
        dinners += [food(f'Другой ужин {n}',111,1,1,1,'Ужин') for n in range(398)]
        lunches.append(food('Нужный обед',700,25,25,100,'Обед'))
        dinners.append(food('Нужный ужин',800,35,28,80,'Ужин'))
        with patch('core.random.Random',FirstChoiceRandom):
            week=plan([normal,corn]+lunches+dinners,required_ids=[recipe_key(corn)],target=2000,tolerance=0,macro_tolerance=0,seed=2)
        self.assertTrue(any(r.uid==corn.uid for day in week for r in day))
        day=next(day for day in week if corn in day)
        self.assertEqual(day[1].name,'Нужный обед')
        self.assertEqual(day[2].name,'Нужный ужин')

    def test_true_conflict_gives_actual_nutrient_range(self):
        normal=food('Обычное',2000/3,25,67/3,275/3,'Любой')
        corn=food('Кукурузная каша',3000,25,20,90,'Любой')
        with self.assertRaisesRegex(ValueError,'Калории, ккал: с этим блюдом возможно') as error:
            plan([normal,food("Второе обычное",2000/3,25,67/3,275/3,"Любой"),corn],required_ids=[recipe_key(corn)],seed=1)
        self.assertIn('1800.0–2200.0',str(error.exception))
        self.assertIn('Все дневные сочетания проверены',str(error.exception))
        week=plan([normal,food("Второе обычное",2000/3,25,67/3,275/3,"Любой"),corn],required_ids=[recipe_key(corn)],require_nutrition=False,seed=1)
        self.assertTrue(any(r.uid==corn.uid for day in week for r in day))

class DiagnosticTests(unittest.TestCase):
    def test_local_rotating_log_captures_settings_failure_and_not_recipe_body(self):
        with tempfile.TemporaryDirectory() as directory:
            logger,path=configure_logging(Path(directory)/'logs')
            r=food('Кукурузная каша',3000,25,20,90,'Любой')
            r.method='PRIVATE METHOD SENTINEL'
            r.source_url='https://example.com/?secret=NOT_FOR_LOGS'
            log_plan(logger,'request123',{'required_ids':[recipe_key(r)],'kcal':2000,'require_nutrition':True,'not_allowed':'SECRET SENTINEL'},[r])
            normal=food('Обычное',2000/3,25,67/3,275/3,'Любой')
            try:plan([normal,food("Второе обычное",2000/3,25,67/3,275/3,"Любой"),r],required_ids=[recipe_key(r)])
            except ValueError:logger.exception('request=request123 operation_failed')
            self.assertEqual(logger.handlers[0].backupCount,3)
            close_logging(logger)
            content=path.read_text(encoding='utf-8')
            for expected in (f'version={APP_VERSION}','request123','Кукурузная каша','anchored_search','Traceback','Калории, ккал','+03:00'):
                self.assertIn(expected,content)
            for absent in ('PRIVATE METHOD SENTINEL','NOT_FOR_LOGS','SECRET SENTINEL'):
                self.assertNotIn(absent,content)
