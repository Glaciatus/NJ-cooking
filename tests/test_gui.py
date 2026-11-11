"""Real Tk widget workflows; requires Windows or an X11 DISPLAY on Linux."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from app import App, IngredientDialog
from core import Ingredient
from importing import parse_page
from storage import load_recipes

@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'GUI needs Windows or X11 DISPLAY')
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/'recipes.json'
        self.errors = []
        self.patches = [patch('app.messagebox.showerror', side_effect=lambda *a, **k: self.errors.append(a)),
                        patch('app.messagebox.showinfo'), patch('app.messagebox.askyesnocancel', return_value=False)]
        for p in self.patches:
            p.start()
        self.app=App(self.path)
        self.callback_errors=[]
        self.app.report_callback_exception=lambda *args: self.callback_errors.append(args)
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        for p in self.patches:
            p.stop()
        self.directory.cleanup()
        self.assertFalse(self.callback_errors)

    def test_blank_calories_save_estimate_edit_reload(self):
        a=self.app
        a.fields['name'].set('Каша')
        a.fields['servings'].set('4')
        a.ingredients_data=[Ingredient('Рис',400,'г')]
        a.refresh_ingredients()
        self.assertTrue(a.save_recipe())
        self.assertIsNone(load_recipes(self.path)[0].kcal)
        self.assertIn('365', a.nutrition_preview.cget('text'))
        a.fields['name'].set('Рисовая каша')
        self.assertTrue(a.save_recipe())
        self.assertEqual(len(load_recipes(self.path)),1)
        self.assertTrue(self.path.with_suffix('.json.bak').exists())

    def test_missing_fields_save_draft_and_readable_invalid_number(self):
        a=self.app
        a.fields['name'].set('Черновик')
        self.assertTrue(a.save_recipe())
        self.assertIn('Черновик сохранён',a.status.get())
        a.fields['kcal'].set('не знаю')
        self.assertFalse(a.save_recipe())
        self.assertIn('Калории: введите число',a.status.get())
        self.assertEqual(load_recipes(self.path)[0].name,'Черновик')

    def test_week_generation_empty_targets_and_export_content(self):
        a=self.app
        a.add_examples()
        for key in ('people','portions','kcal','protein','fat','carbs','tolerance','macro_tolerance'):
            a.settings[key].set('')
        a.generate()
        deadline=time.monotonic()+5
        while a.busy and time.monotonic()<deadline:
            a.update()
            time.sleep(.01)
        self.assertFalse(a.busy)
        self.assertEqual(len(a.week),7)
        self.assertIn('ИТОГО ЗА НЕДЕЛЮ',a.report)
        self.assertEqual(str(a.export_button.cget('state')),'normal')
        self.assertFalse(self.errors)

    def test_import_source_review_and_preservation(self):
        a=self.app
        recipes=parse_page('<script type="application/ld+json">{"@type":"Recipe","name":"Тест","recipeIngredient":["100 г рис"],"recipeYield":1}</script>','https://example.com/recipe')
        a.receive_imports(recipes)
        self.assertFalse(a.recipes[0].reviewed)
        self.assertEqual(a.fields['source_url'].get(),'https://example.com/recipe')
        self.assertTrue(a.save_recipe())
        self.assertTrue(load_recipes(self.path)[0].reviewed)
        self.assertEqual(load_recipes(self.path)[0].source_url,'https://example.com/recipe')

    def test_ingredient_dialog_missing_amount_and_custom_values(self):
        dialog=IngredientDialog(self.app)
        dialog.name.set('Соус')
        dialog.save()
        self.assertEqual(dialog.result.name,'Соус')
        self.assertIsNone(dialog.result.amount)
        dialog=IngredientDialog(self.app)
        dialog.name.set('Соус')
        dialog.values[0].set('100')
        dialog.save()
        self.assertIsNone(dialog.result)
        self.assertIn('все четыре',dialog.error.cget('text'))
        dialog.destroy()

    def test_small_window_primary_actions_visible(self):
        a=self.app
        a.geometry('1000x700')
        a.tabs.select(a.settings_tab)
        a.update()
        self.assertTrue(a.generate_button.winfo_ismapped())
        self.assertLess(a.generate_button.winfo_rooty()+a.generate_button.winfo_height(), a.winfo_rooty()+a.winfo_height())

    def test_edit_current_week_tags_portions_and_recalculate_without_replacing_dishes(self):
        a=self.app
        a.add_examples();a.generate()
        deadline=time.monotonic()+5
        while a.busy and time.monotonic()<deadline:a.update();time.sleep(.01)
        self.assertFalse(a.busy)
        original_ids=[[r.uid for r in day] for day in a.week]
        a.week_tree.selection_set('0-0')
        a.edit_week_recipe()
        uid=a.editor_uid
        a.fields['name'].set('Исправленный рецепт недели')
        a.fields['servings'].set('2')
        a.fields['kcal'].set('300')
        a.recipe_tag_vars['Десерт'].set(True)
        self.assertTrue(a.save_recipe())
        self.assertEqual(a.recipes[a.current].uid,uid)
        self.assertIn('изменён',a.week_message.get())
        self.assertEqual(str(a.export_button.cget('state')),'disabled')
        a.recalculate_week()
        self.assertEqual([[r.uid for r in day] for day in a.week],original_ids)
        revised=next(r for day in a.week for r in day if r.uid==uid)
        self.assertEqual(revised.kcal,300)
        self.assertEqual(revised.servings,2)
        self.assertIn('Десерт',revised.tags)
        self.assertIn('Исправленный рецепт недели',a.report)
        self.assertEqual(str(a.export_button.cget('state')),'normal')
        self.assertTrue(a.menu_path.exists())
        self.assertFalse(self.errors)

    def test_replan_current_pool_keeps_saved_settings(self):
        a=self.app;a.add_examples();a.generate()
        deadline=time.monotonic()+5
        while a.busy and time.monotonic()<deadline:a.update();time.sleep(.01)
        pool={r.uid for day in a.week for r in day}
        context=dict(a.last_plan_settings)
        a.settings['people'].set('999')
        a.replan_current()
        deadline=time.monotonic()+5
        while a.busy and time.monotonic()<deadline:a.update();time.sleep(.01)
        self.assertFalse(a.busy)
        self.assertTrue({r.uid for day in a.week for r in day}<=pool)
        self.assertEqual(a.last_plan_settings,context)
        self.assertFalse(self.errors)

    def test_ingredient_preserves_usda_selection_and_can_disable_range_estimate(self):
        i=Ingredient('Продукт',None,'шт',fdc_id=171287,amount_estimate=2.5,amount_basis='2-3 шт')
        dialog=IngredientDialog(self.app,i)
        self.assertEqual(dialog.fdc_id,171287)
        dialog.keep_estimate.set(False)
        dialog.save()
        self.assertEqual(dialog.result.fdc_id,171287)
        self.assertIsNone(dialog.result.amount_estimate)
