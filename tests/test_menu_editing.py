from collections import Counter
import unittest
from core import Recipe,Ingredient,recipe_key
from menu_editing import replace_dish,swap_dishes,move_dish,arrangement_warnings
from nutrition import nutrition_totals,DEFAULT_TARGETS
from reports import products_text,week_report

class MenuEditTests(unittest.TestCase):
    def setUp(self):
        self.recipes=[Recipe(f'Рецепт {n}',1,100+n,[Ingredient('Рис',10+n,'г')],protein=1,fat=1,carbs=1,database_id='personal') for n in range(21)]
        self.week=[tuple(self.recipes[d*3:d*3+3]) for d in range(7)]
    def test_replace_changes_day_and_week_totals_without_mutating_original(self):
        new=Recipe('Замена',1,999,[Ingredient('Рис',200,'г')],protein=20,fat=20,carbs=20,database_id='personal')
        changed=replace_dish(self.week,(0,0),new)
        self.assertEqual(self.week[0][0].name,'Рецепт 0')
        self.assertEqual(changed[0][0].name,'Замена')
        self.assertEqual(nutrition_totals([(r,1) for r in changed[0]])['kcal'],999+101+102)
        self.assertIn('рис: 223 г',products_text([(r,1) for r in changed[0]]))
        old_week=nutrition_totals([(r,1) for day in self.week for r in day])
        new_week=nutrition_totals([(r,1) for day in changed for r in day])
        self.assertEqual(new_week['kcal']-old_week['kcal'],899)
    def test_swap_between_days_and_meal_times_preserves_weekly_products(self):
        changed=swap_dishes(self.week,(0,0),(6,2))
        self.assertIs(changed[0][0],self.recipes[20])
        self.assertIs(changed[6][2],self.recipes[0])
        self.assertEqual(products_text([(r,1) for day in changed for r in day]),products_text([(r,1) for day in self.week for r in day]))
    def test_move_inserts_and_shifts_all_intermediate_slots_without_loss(self):
        changed=move_dish(self.week,(0,0),(2,2))
        flat=[r for day in changed for r in day]
        self.assertIs(flat[8],self.recipes[0])
        self.assertEqual(flat[:8],self.recipes[1:9])
        self.assertEqual(Counter(recipe_key(r) for r in flat),Counter(recipe_key(r) for r in self.recipes))
        restored=move_dish(changed,(2,2),(0,0))
        self.assertEqual(restored,self.week)
    def test_conflicts_warn_instead_of_discarding_manual_change(self):
        r=self.recipes[0];r.meal='Завтрак'
        changed=replace_dish(self.week,(0,0),self.recipes[1])
        context={'required_ids':[recipe_key(r)],'required_names':{recipe_key(r):r.name},'excluded':['рис'],'database_limits':{'personal':20}}
        warnings=arrangement_warnings(changed,context,{'personal'})
        self.assertTrue(any('Удалены обязательные' in x for x in warnings))
        self.assertTrue(any('исключённые продукты' in x for x in warnings))
        report=week_report(changed,2,1,DEFAULT_TARGETS,200,.2,False,extra_warnings=warnings)
        self.assertIn('Удалены обязательные блюда: Рецепт 0',report)
        changed=swap_dishes(self.week,(0,0),(0,2))
        self.assertTrue(any('в карточке указано' in w for w in arrangement_warnings(changed,{})))
    def test_invalid_positions_cannot_delete_or_extend_week(self):
        for bad in ((-1,0),(7,0),(0,3)):
            with self.assertRaises(ValueError):move_dish(self.week,bad,(0,0))
        with self.assertRaises(ValueError):swap_dishes(self.week[:2],(0,0),(0,1))
