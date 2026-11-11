"""Integration contracts for bundled data, estimates, filters and menu revisions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from catalog import records, search_foods
from core import Ingredient,Recipe,plan,readiness,refresh_week,totals
from estimation import servings_info
from nutrition import recipe_nutrition,ingredient_mass,reference_food,DEFAULT_TARGETS
from reports import week_report,week_issues
from storage import load_library,save_library,bundled_recipes,save_recipes
from tagging import recipe_tags,infer_tags

class DataTests(unittest.TestCase):
    def test_official_catalog_and_explicit_food_choice(self):
        self.assertEqual(len(records()),8202)
        self.assertTrue(any(r['dataset']=='Foundation' for r in records().values()))
        self.assertEqual(reference_food('рис').fdc_id,169756)
        self.assertNotEqual(reference_food('рис').fdc_id,reference_food('рис вареный').fdc_id)
        self.assertTrue(search_foods('169756'))
        self.assertTrue(search_foods('рис'))
        i=Ingredient('Мой продукт',100,'г',fdc_id=171287)
        r=Recipe('Блюдо',1,None,[i])
        self.assertEqual(recipe_nutrition(r)[0]['kcal'],143)
        i.per100g=[200,10,10,10]
        self.assertEqual(recipe_nutrition(r)[0]['kcal'],200)

    def test_builtin_library_no_approvals_and_preserve_user_data(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'recipes.json'
            local=Recipe('Мой рецепт',1,500,[Ingredient('Рис',100,'г')],protein=20,fat=15,carbs=70)
            save_recipes(path,[local])
            library=load_library(path)
            self.assertEqual(len(library),13704)
            self.assertTrue(all(r.reviewed for r in bundled_recipes()))
            built=library[0];uid=built.uid;built.name='Моя правка встроенного рецепта';built.servings=7
            library.pop(1)
            save_library(path,library)
            payload=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(payload['format'],2)
            self.assertEqual(len(payload['overrides']),2)
            self.assertEqual(len(payload['hidden_ids']),1)
            restored=load_library(path)
            self.assertEqual(len(restored),13703)
            self.assertEqual(next(r for r in restored if r.uid==uid).servings,7)
            self.assertTrue(any(r.uid==local.uid for r in restored))
            self.assertEqual(len(json.loads(path.with_suffix('.json.bak').read_text(encoding='utf-8'))),1)
            self.assertNotEqual(bundled_recipes()[0].name,'Моя правка встроенного рецепта')

    def test_legacy_recipe_matches_bundle_by_source_without_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'recipes.json'
            r=copy.deepcopy(bundled_recipes()[0]);r.uid='old-id';r.tags=None;r.source_category='';r.servings=17;r.kcal=321
            save_recipes(path,[r])
            library=load_library(path)
            self.assertEqual(len(library),13703)
            restored=next(x for x in library if x.source_url==r.source_url)
            self.assertEqual(restored.servings,17)
            self.assertEqual(restored.kcal,321)
            self.assertTrue(restored.tags)

class EstimateTests(unittest.TestCase):
    def test_soup_weight_explicit_water_not_counted_twice(self):
        r=Recipe('Рисовый суп',None,None,[Ingredient('Рис',100,'г'),Ingredient('Вода',1000,'г')],tags=['Суп'])
        estimate=servings_info(r)
        self.assertTrue(estimate.estimated)
        self.assertEqual(estimate.output_g,1100)
        self.assertEqual(estimate.servings,3)
        self.assertIn('350',estimate.explanation)
        r.servings=9
        self.assertEqual(servings_info(r).servings,9)
        self.assertFalse(servings_info(r).estimated)

    def test_dry_grain_absorbs_water_and_manual_override_changes_nutrients(self):
        r=Recipe('Рисовая каша',None,None,[Ingredient('Рис',200,'г')],tags=['Каша'])
        estimate=servings_info(r)
        self.assertEqual(estimate.output_g,560)
        self.assertEqual(estimate.servings,2)
        before=recipe_nutrition(r)[0]['kcal']
        r.servings=4
        self.assertEqual(recipe_nutrition(r)[0]['kcal'],before/2)

    def test_no_generic_two_serving_fallback_for_unknown_or_preserves(self):
        r=Recipe('Неизвестное блюдо',None,None,[Ingredient('Неизвестное',None,'')])
        self.assertIsNone(servings_info(r).servings)
        r=Recipe('Варенье',None,None,[Ingredient('Сахар',1000,'г')],tags=['Заготовка'])
        self.assertIsNone(servings_info(r).servings)

    def test_small_unknown_seasonings_do_not_block_yield_or_become_zero_nutrients(self):
        r=Recipe('Овощной суп',None,None,[Ingredient('Морковь',400,'г'),Ingredient('Вода',1000,'мл'),Ingredient('Соль',None,'')],tags=['Суп'])
        self.assertIsNotNone(servings_info(r).servings)
        self.assertIn('приправ',servings_info(r).explanation)
        self.assertIsNone(recipe_nutrition(r)[0]['kcal'])
        self.assertFalse(readiness(r,False))
        self.assertTrue(readiness(r,True))

    def test_average_units_and_explicit_quantity_estimates(self):
        self.assertEqual(ingredient_mass(Ingredient('Лук репчатый',2,'шт')),220)
        self.assertEqual(ingredient_mass(Ingredient('Чеснок',2,'зубчика')),6)
        self.assertEqual(ingredient_mass(Ingredient('Чеснок',1,'головка')),40)
        self.assertEqual(ingredient_mass(Ingredient('Яйца',None,'шт',amount_estimate=2.5)),125)
        self.assertGreater(ingredient_mass(Ingredient('Мука',1,'стакан')),100)
        self.assertIsNone(ingredient_mass(Ingredient('Неизвестный продукт',2,'шт')))

class RevisionTests(unittest.TestCase):
    def recipe(self,name='Блюдо'):
        return Recipe(name,2,500,[Ingredient('Рис',400,'г')],protein=20,fat=15,carbs=70,tags=['Мясное блюдо'])

    def test_tag_filter_and_missing_nutrition_switch(self):
        selected=self.recipe('Выбранное');selected.kcal=None;selected.protein=None;selected.fat=None;selected.carbs=None
        selected.ingredients=[Ingredient('Фирменный продукт',100,'г')]
        other=self.recipe('Десерт');other.tags=['Десерт']
        allowed=[selected,self.recipe('Второе мясное'),self.recipe('Третье мясное')]
        week=plan(allowed+[other],require_nutrition=False,desired_tags=['Мясное блюдо'],seed=2)
        self.assertTrue(all(r.uid in {x.uid for x in allowed} for day in week for r in day))
        with self.assertRaises(ValueError):plan([selected],require_nutrition=True)
        report=week_report(week,2,1,DEFAULT_TARGETS,200,.2,False)
        self.assertIn('известно частично',report)
        self.assertIn('НЕ полный итог',report)
        self.assertIn('выключен',report)

    def test_recalculation_preserves_all_21_slots_after_rename_and_serving_change(self):
        r=self.recipe()
        week=[(r,r,r)]*7  # Legacy saved arrangement: refresh preserves positions, rather than generating duplicates.
        edited=copy.deepcopy(r);edited.name='Новое имя';edited.servings=4;edited.kcal=700
        new=refresh_week(week,[edited])
        self.assertTrue(all(x.name=='Новое имя' for day in new for x in day))
        self.assertEqual(totals([(new[0][0],2)])[('рис','г')],200)
        self.assertEqual(totals([(week[0][0],2)])[('рис','г')],400)
        self.assertTrue(week_issues(new,1,DEFAULT_TARGETS,0,0))
        with self.assertRaisesRegex(ValueError,'удалены'):refresh_week(week,[])

    def test_manual_tags_and_auto_tags(self):
        tags=infer_tags('Курица в соусе',ingredients=[Ingredient('Куриное филе',100,'г')])
        self.assertIn('Птица',tags)
        self.assertNotIn('Соус',tags)
        r=self.recipe();r.tags=[]
        self.assertEqual(recipe_tags(r),[])

class VariantPreservationTests(unittest.TestCase):
    def test_two_personal_variants_with_same_source_are_not_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'recipes.json'
            original=copy.deepcopy(bundled_recipes()[0])
            variant=copy.deepcopy(original);variant.uid='personal-variant';variant.name+=' мой вариант';variant.kcal=123
            save_recipes(path,[variant,original])  # Variant deliberately comes first.
            result=load_library(path)
            self.assertEqual(len(result),13704)
            self.assertTrue(any(r.uid=='personal-variant' and r.kcal==123 for r in result))
            save_library(path,result)
            self.assertEqual(len(load_library(path)),13704)
