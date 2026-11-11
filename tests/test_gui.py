from diagnostics import APP_VERSION
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

    def test_nutrition_preview_requires_acceptance_and_keeps_original_settings(self):
        a=self.app;a.add_examples()
        context={**a.read_settings(),'require_nutrition':True,'desired_tags':[],
                 'required_ids':[],'database_limits':{},'enabled_databases':['personal'],'excluded':[],'wanted':[]}
        recipes=a.manager.active_recipes()
        week=[tuple(recipes[:3])]*7
        a.week=week;a.last_plan_settings=context;a.render_week()
        before=a.menu_path.read_bytes();report=a.report
        def synchronous(work,done,*args,**kwargs):done(work())
        for accept in (False,True):
            with patch.object(a,'run_background',side_effect=synchronous), patch('app.plan',side_effect=[__import__('core').NutritionSearchFailure('Предел жиров'),week]) as planner, patch.object(a,'confirm_nutrition_preview',return_value=accept) as confirm:
                a.start_plan(context,recipes)
            confirm.assert_called_once()
            self.assertTrue(planner.call_args_list[1].kwargs['allow_nutrition_deviations'])
            self.assertTrue(planner.call_args_list[1].kwargs['require_nutrition'])
            if not accept:
                self.assertEqual(a.menu_path.read_bytes(),before)
                self.assertEqual(a.report,report)
            else:
                self.assertTrue(a.last_plan_settings['accepted_nutrition_deviations'])
                self.assertTrue(a.last_plan_settings['require_nutrition'])
                self.assertIn('с отклонениями',a.plan_message.cget('text'))

    def test_preview_dialog_has_explicit_accept_and_cancel_actions(self):
        a=self.app;a.add_examples()
        context={**a.read_settings(),'require_nutrition':True,'database_limits':{}}
        week=[tuple(a.manager.active_recipes()[:3])]*7
        def click_accept():
            def find(widget):
                for child in widget.winfo_children():
                    if child.winfo_class()=='TButton' and child.cget('text').startswith('Принять меню'):
                        child.invoke();return True
                    if find(child):return True
                return False
            self.assertTrue(find(a))
        a.after(80,click_accept)
        self.assertTrue(a.confirm_nutrition_preview(week,context,'Не удалось найти строгий вариант'))

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

    def test_day_menu_has_full_recipe_and_day_navigation(self):
        a=self.app;a.add_examples();a.generate()
        deadline=time.monotonic()+5
        while a.busy and time.monotonic()<deadline:a.update();time.sleep(.01)
        self.assertEqual(len(a.tabs.tabs()),4)
        self.assertEqual(len(a.day_recipes.get_children()),3)
        a.menu_day.set('День 2');a.update()
        self.assertIn(a.week[1][0].name,a.day_reader.get('1.0','end'))
        self.assertIn('ПРИГОТОВЛЕНИЕ',a.day_reader.get('1.0','end'))
        self.assertIn('КБЖУ на человека',a.day_summary.cget('text'))
        self.assertNotIn('КБЖУ за день на семью',a.report)
        a.edit_day_recipe();a.update()
        self.assertTrue(a.editor_expanded)
        a.toggle_editor();self.assertFalse(a.editor_expanded)

    def test_required_checkboxes_persist_and_reset_needs_confirmation(self):
        a=self.app;a.add_examples()
        a.update()
        box=a.library.bbox('0','required')
        self.assertTrue(box)
        a.library.event_generate('<Button-1>',x=box[0]+10,y=box[1]+10)
        a.update()
        self.assertEqual(len(a.manager.required_keys()),1)
        with patch('app.messagebox.askyesno',return_value=False) as confirm:
            a.reset_required()
            self.assertEqual(len(a.manager.required_keys()),1)
            confirm.assert_called_once()
        with patch('app.messagebox.askyesno',return_value=True):a.reset_required()
        self.assertFalse(a.manager.required_keys())

    def test_personal_only_generation_and_required_recipe(self):
        a=self.app;a.add_examples()
        a.toggle_required(0)
        a.generate()
        deadline=time.monotonic()+5
        while a.busy and time.monotonic()<deadline:a.update();time.sleep(.01)
        self.assertFalse(a.busy)
        self.assertTrue(all(r.database_id=='personal' for day in a.week for r in day))
        self.assertTrue(any(r.uid==a.recipes[0].uid for day in a.week for r in day))
        self.assertFalse(self.errors)

    def test_failed_plan_writes_diagnostics_and_displays_log_path(self):
        a=self.app;a.add_examples()
        with patch('app.plan',side_effect=ValueError('Невыполнимая квота базы')):
            a.generate()
            deadline=time.monotonic()+10
            while a.busy and time.monotonic()<deadline:a.update();time.sleep(.01)
        self.assertFalse(a.busy)
        self.assertTrue(self.errors)
        self.assertIn('Журнал диагностики:',self.errors[-1][1])
        content=a.log_path.read_text(encoding='utf-8')
        for text in (f'version={APP_VERSION}','plan_settings','database_sources','operation_failed','Traceback','Невыполнимая квота базы'):
            self.assertIn(text,content)

    def test_manual_replace_recalculates_persists_and_undoes(self):
        from menu_editing import replace_dish,swap_dishes,move_dish
        from core import recipe_key
        import json
        a=self.app;a.add_examples();a.generate()
        deadline=time.monotonic()+5
        while a.busy and time.monotonic()<deadline:a.update();time.sleep(.01)
        before=[[recipe_key(r) for r in day] for day in a.week]
        replacement=next(r for r in a.recipes if recipe_key(r)!=recipe_key(a.week[0][0]))
        self.assertTrue(a.apply_menu_change(replace_dish(a.week,(0,0),replacement),'Тест замены',(0,0)))
        self.assertEqual(a.week[0][0].uid,replacement.uid)
        saved=json.loads(a.menu_path.read_text())
        self.assertEqual(saved['uids'][0][0],recipe_key(replacement))
        self.assertIn(replacement.name,a.report)
        a.undo_menu_change()
        self.assertEqual([[recipe_key(r) for r in day] for day in a.week],before)
        self.assertEqual(str(a.undo_button.cget('state')),'disabled')
        original=a.week[0][0]
        self.assertTrue(a.apply_menu_change(swap_dishes(a.week,(0,0),(2,2)),'Обмен',(2,2)))
        self.assertEqual(a.week[2][2].uid,original.uid)
        self.assertIn('День 3',a.menu_day.get())
        a.undo_menu_change()
        self.assertTrue(a.apply_menu_change(move_dish(a.week,(0,0),(6,2)),'Перенос',(6,2)))
        self.assertEqual(a.week[6][2].uid,original.uid)
        self.assertFalse(self.errors)

    def test_imported_source_nutrition_is_preserved_when_card_is_saved(self):
        from importing import import_html
        a=self.app
        path=Path(__file__).parent/'fixtures'/'povar-microdata.html'
        a.receive_imports(import_html(path))
        a.fields['name'].set('Мои спагетти')
        self.assertTrue(a.save_recipe())
        r=load_recipes(self.path)[0]
        self.assertEqual(r.source_nutrition_per100g['kcal'],299)
        self.assertIsNone(r.kcal)
        self.assertTrue(r.image_url)

    def test_manual_change_write_failure_preserves_menu_and_report(self):
        from menu_editing import swap_dishes
        a=self.app;a.add_examples();a.generate()
        deadline=time.monotonic()+5
        while a.busy and time.monotonic()<deadline:a.update();time.sleep(.01)
        old=a.week;report=a.report
        with patch('app.save_json',side_effect=OSError('disk full')):
            self.assertFalse(a.apply_menu_change(swap_dishes(old,(0,0),(0,1)),'Обмен'))
        self.assertEqual(a.week,old)
        self.assertEqual(a.report,report)
        self.assertFalse(a.menu_history)

    def test_replacement_and_move_dialogs_apply_actual_widget_choices(self):
        from menu_dialogs import ReplaceDialog,MoveDialog
        from core import recipe_key
        a=self.app;a.add_examples();a.generate()
        deadline=time.monotonic()+5
        while a.busy and time.monotonic()<deadline:a.update();time.sleep(.01)
        original=a.week[0][0]
        dialog=ReplaceDialog(a,(0,0));a.update()
        candidate=next(r for r in a.recipes if recipe_key(r)!=recipe_key(original))
        dialog.tree.selection_set(recipe_key(candidate));dialog.show_preview();dialog.apply();a.update()
        self.assertEqual(a.week[0][0].uid,candidate.uid)
        dialog=MoveDialog(a,(0,0))
        dialog.day.set('День 2');dialog.meal.set('Вечер · ужин');dialog.apply();a.update()
        self.assertEqual(a.week[1][2].uid,candidate.uid)
        self.assertFalse(self.errors)
