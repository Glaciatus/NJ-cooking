import copy
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from core import Recipe,Ingredient,plan,recipe_key,refresh_week,totals
from databases import DatabaseManager
from reports import week_report,products_text
from nutrition import DEFAULT_TARGETS
from storage import save_library,save_recipes,bundled_recipes,load_recipes


def recipe(name,db='personal',meal='Любой'):
    return Recipe(name,1,650,[Ingredient('Рис',100,'г')],protein=25,fat=20,carbs=90,database_id=db,meal=meal)

class DatabaseTests(unittest.TestCase):
    def test_migrate_to_separate_files_and_preserve_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            old=Path(directory)/'recipes.json'
            personal=recipe('Свой рецепт',db='')
            base=copy.deepcopy(bundled_recipes())
            base[0].name='Моя правка большой базы'
            save_library(old,base+[personal],True)
            original=old.read_bytes()
            manager=DatabaseManager(old,True)
            self.assertNotEqual(manager.get('bundled').path,manager.get('personal').path)
            self.assertEqual(manager.get('personal').path.name,'personal-recipes.json')
            self.assertEqual(manager.get('bundled').recipes[0].name,'Моя правка большой базы')
            self.assertEqual(len(manager.get('personal').recipes),1)
            self.assertEqual(old.read_bytes(),original)
            active=manager.active_recipes()
            big_bytes=manager.get('bundled').path.read_bytes()
            changed=copy.deepcopy(manager.get('personal').recipes[0]);changed.name='Личная правка'
            manager.save_all([changed if recipe_key(r)==recipe_key(changed) else r for r in active])
            self.assertEqual(manager.get('bundled').path.read_bytes(),big_bytes)
            self.assertEqual(load_recipes(manager.get('personal').path)[0].name,'Личная правка')

    def test_disabled_database_and_favourites_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'personal.json'
            manager=DatabaseManager(path,False)
            one=recipe('Личный')
            manager.save_all([one]);manager.toggle_required(one)
            other_path=Path(directory)/'other.json';save_recipes(other_path,[recipe('Другой',db='')])
            other=manager.connect(other_path)
            manager.toggle_required(other.recipes[0])
            other.enabled=False;manager.persist()
            self.assertEqual({r.name for r in manager.active_recipes()},{'Личный'})
            self.assertEqual(manager.required_keys(),[recipe_key(one)])
            restored=DatabaseManager(path,False)
            self.assertEqual(len(restored.get(other.uid).required),1)
            self.assertFalse(restored.get(other.uid).enabled)
            self.assertEqual(restored.required_keys(),[recipe_key(one)])

    def test_create_connect_existing_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'main.json';manager=DatabaseManager(path,False)
            custom=Path(directory)/'custom.json';save_recipes(custom,[recipe('Не потерять',db='')])
            custom.write_bytes(b'\xef\xbb\xbf'+custom.read_bytes())
            original=custom.read_bytes()
            with self.assertRaises(ValueError):manager.create(custom)
            self.assertEqual(custom.read_bytes(),original)
            manager.connect(custom)
            with self.assertRaises(ValueError):manager.connect(custom)
            invalid=Path(directory)/'invalid.json';invalid.write_text('{"FoundationFoods": []}')
            with self.assertRaises(ValueError):manager.connect(invalid)
            reserved=Path(directory)/'menu.json'
            with self.assertRaises(ValueError):manager.create(reserved)
            self.assertFalse(reserved.exists())

    def test_same_recipe_id_in_two_files_keeps_independent_week_links(self):
        a=recipe('Один','a');b=copy.deepcopy(a);b.database_id='b';b.name='Другой'
        week=[(a,b,a)]*7
        revised=copy.deepcopy(b);revised.name='Правка только Б'
        resolved=refresh_week(week,[a,revised])
        self.assertEqual(resolved[0][0].name,'Один')
        self.assertEqual(resolved[0][1].name,'Правка только Б')

class SelectionTests(unittest.TestCase):
    def test_required_recipes_and_exact_database_counts(self):
        recipes=[recipe(f'{db}-{i}',db) for db in ('big','personal') for i in range(8)]
        required=[recipe_key(r) for r in recipes[8:13]]
        week=plan(recipes,require_nutrition=False,required_ids=required,database_limits={'big':11,'personal':10},seed=3)
        self.assertEqual(Counter(r.database_id for day in week for r in day),{'big':11,'personal':10})
        self.assertTrue(set(required)<={recipe_key(r) for day in week for r in day})

    def test_all_21_required_recipes_are_used(self):
        recipes=[recipe(f'{meal}-{i}',meal=meal) for meal in ('Завтрак','Обед','Ужин') for i in range(7)]
        required=[recipe_key(r) for r in recipes]
        week=plan(recipes,require_nutrition=False,required_ids=required,seed=5)
        self.assertEqual({recipe_key(r) for day in week for r in day},set(required))

    def test_impossible_favourites_and_quotas_report_conflict(self):
        recipes=[recipe(f'Завтрак {i}',meal='Завтрак') for i in range(8)]+[recipe('Остальное')]
        with self.assertRaisesRegex(ValueError,'мест только 7'):
            plan(recipes,required_ids=[recipe_key(r) for r in recipes[:8]],require_nutrition=False)
        with self.assertRaisesRegex(ValueError,'сумма должна быть 21'):
            plan([recipe('Один')],database_limits={'personal':10},require_nutrition=False)
        with self.assertRaisesRegex(ValueError,'больше 21'):
            many=[recipe(str(n)) for n in range(22)]
            plan(many,required_ids=[recipe_key(r) for r in many],require_nutrition=False)
        with self.assertRaisesRegex(ValueError,'не остаётся мест'):
            private=recipe('Обязательный из личной');big=recipe('Большой','big')
            plan([private,big],required_ids=[recipe_key(private)],database_limits={'big':21},require_nutrition=False)
        bad=recipe('Исключённый')
        with self.assertRaisesRegex(ValueError,'Обязательные рецепты'):
            plan([bad],required_ids=[recipe_key(bad)],excluded=['рис'],require_nutrition=False)

    def test_products_are_additive_and_nutrition_only_per_person(self):
        r=recipe('Мука')
        r.ingredients=[Ingredient('мука',2490,'г'),Ingredient('мука',3.6,'стакана'),Ingredient('мука пшеничная',6,'ст. л.')]
        values=totals([(r,1)])
        self.assertEqual(values[('мука','г')],2490)
        self.assertEqual(values[('мука','стакана')],3.6)
        self.assertEqual(values[('мука пшеничная','ст. л')],6)
        text=week_report([(r,r,r)]*7,2,1,DEFAULT_TARGETS,200,.2,False)
        self.assertNotIn('КБЖУ за день на семью',text)
        self.assertNotIn('КБЖУ на семью',text)
        self.assertIn('это не варианты замены',text)
