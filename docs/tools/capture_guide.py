"""Capture the real Tk 0.8.1 UI with temporary numbered widgets for the guide.

Documentation tool, Linux/X11 + ImageMagick `import`; no user data is opened.
Run from repository root: DISPLAY=:99 /usr/bin/python3 docs/tools/capture_guide.py
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import copy
import subprocess
import tempfile
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
from app import App,IngredientDialog
from core import plan,recipe_key
from reports import balance_options
from menu_dialogs import ReplaceDialog,MoveDialog

OUT=Path(__file__).resolve().parents[1]/'images'
OUT.mkdir(exist_ok=True)


def walk(root):
    for child in root.winfo_children():
        yield child
        yield from walk(child)


def button(root,text):
    return next(w for w in walk(root) if w.winfo_class() in ('TButton','TCheckbutton','TRadiobutton') and w.cget('text')==text and w.winfo_ismapped())


def variable(root,var):
    return next(w for w in walk(root) if w.winfo_class() in ('TEntry','TCombobox') and str(w.cget('textvariable'))==str(var) and w.winfo_ismapped())


def canvas_of(widget):
    return next(w for w in walk(widget) if isinstance(w,tk.Canvas))


def capture(root,name,marks):
    root.update()
    overlays=[]
    for num,target in enumerate(marks,1):
        if isinstance(target,tuple):
            widget,x,y,width,height=target
            x+=widget.winfo_rootx()-root.winfo_rootx();y+=widget.winfo_rooty()-root.winfo_rooty()
        else:
            widget=target;x=widget.winfo_rootx()-root.winfo_rootx();y=widget.winfo_rooty()-root.winfo_rooty()
            width=widget.winfo_width();height=widget.winfo_height()
        if not (-5<=x<root.winfo_width() and -5<=y<root.winfo_height()):raise RuntimeError(f'{name}: marker {num} is outside view')
        for xx,yy,ww,hh in ((x,y,width,2),(x,y+height-2,width,2),(x,y,2,height),(x+width-2,y,2,height)):
            line=tk.Frame(root,bg='#c62b31',borderwidth=0);line.place(x=xx,y=yy,width=ww,height=hh);overlays.append(line)
        label=tk.Label(root,text=str(num),bg='#c62b31',fg='white',font=('Noto Sans',10,'bold'),borderwidth=0)
        label.place(x=max(0,x+width-24),y=max(0,y-12),width=24,height=23);overlays.append(label)
    root.update()
    subprocess.run(['import','-window',str(root.winfo_id()),str(OUT/name)],check=True)
    for widget in overlays:widget.destroy()
    root.update()


with tempfile.TemporaryDirectory(prefix='nj-guide-') as directory,patch('app.messagebox.showinfo'),patch('app.messagebox.askyesnocancel',return_value=False):
    app=App(Path(directory)/'recipes.json',include_bundled=True)
    app.geometry('1360x880+0+0');app.update()
    app.add_examples();app.select_database('personal');app.refresh_library()
    personal=app.manager.get('personal')
    personal.required.add(personal.recipes[0].uid);app.manager.persist();app.update_database_summary();app.refresh_library()
    idx=next(i for i,r in enumerate(app.recipes) if r.database_id=='personal')
    app.load_editor(idx);app.refresh_library();app.update()
    quota=variable(app,app.database_quota)
    search=variable(app,app.search)
    item=str(idx);bbox=app.library.bbox(item,'#1')
    capture(app,'01-bases.png',[app.database_combo,button(app,'Использовать эту БД для меню'),quota,
        button(app,'Подключить JSON…'),button(app,'Создать БД…'),(app.library,*bbox),search,button(app,'Сбросить избранное этой БД…')])
    app.toggle_editor();canvas=canvas_of(app.library_right);canvas.yview_moveto(0);app.update()
    capture(app,'02-recipe.png',[button(app,'Сохранить изменения рецепта'),variable(app,app.fields['servings']),variable(app,app.fields['meal']),
        variable(app,app.fields['kcal']),button(app,'Каша'),button(app,'Определить по названию и составу')])
    canvas.yview_moveto(1);app.update()
    capture(app,'03-ingredients.png',[app.ingredients_tree,button(app,'+ Продукт'),button(app,'Изменить'),button(app,'Вставить список'),app.method,
        variable(app,app.fields['source_url']),button(app,'Открыть источник ↗')])
    ingredient=IngredientDialog(app,personal.recipes[0].ingredients[0]);ingredient.geometry('+170+80');ingredient.update()
    capture(ingredient,'04-ingredient.png',[variable(ingredient,ingredient.name),variable(ingredient,ingredient.amount),variable(ingredient,ingredient.unit),
        button(ingredient,'Выбрать продукт из полной базы USDA…'),variable(ingredient,ingredient.values[0]),variable(ingredient,ingredient.mass),button(ingredient,'Готово')])
    ingredient.choose_usda();ingredient.update()
    usda=next(w for w in ingredient.winfo_children() if isinstance(w,tk.Toplevel));usda.geometry('+160+130');usda.update()
    entry=next(w for w in walk(usda) if w.winfo_class()=='TEntry')
    tree=next(w for w in walk(usda) if w.winfo_class()=='Treeview')
    if tree.get_children():tree.selection_set(tree.get_children()[0])
    capture(usda,'05-usda.png',[entry,button(usda,'Найти'),tree,button(usda,'Использовать выбранный')])
    usda.destroy();ingredient.destroy()
    app.url_dialog();app.update()
    url=next(w for w in app.winfo_children() if isinstance(w,tk.Toplevel));url.geometry('+160+200');url.update()
    entry=next(w for w in walk(url) if w.winfo_class()=='TEntry');entry.insert(0,'https://povar.ru/recipes/neojidannye_spagetti_s_konyakom-62264.html')
    capture(url,'06-link.png',[entry,button(url,'Загрузить и открыть для проверки')]);url.destroy()
    app.toggle_editor();app.tabs.select(app.settings_tab);settings_canvas=canvas_of(app.settings_tab);settings_canvas.yview_moveto(0);app.update()
    app.require_nutrition.set(True)
    capture(app,'07-targets.png',[variable(app,app.settings['people']),variable(app,app.settings['portions']),
        variable(app,app.settings['kcal']),variable(app,app.settings['tolerance']),variable(app,app.settings['macro_tolerance']),
        button(app,'Обязательный контроль КБЖУ — полные данные и соблюдение выбранного режима')])
    app.settings['wanted'].set('банан');app.settings['excluded'].set('огурец')
    settings_canvas.yview_moveto(1);app.update()
    capture(app,'08-balance.png',[variable(app,app.nutrition_mode),variable(app,app.settings['daily_kcal_spread']),
        variable(app,app.settings['daily_macro_spread']),variable(app,app.settings['protein_floor']),button(app,'Каша'),
        variable(app,app.settings['excluded']),variable(app,app.settings['wanted']),app.generate_button])
    # Real planner result on the demonstration library, separate from the user's data.
    app.manager.get('bundled').enabled=False;app.manager.persist()
    context=app.read_settings()
    context.update(require_nutrition=False,desired_tags=[],excluded=['огурец'],wanted=['банан'],required_ids=app.manager.required_keys(),
        required_names={recipe_key(r):r.name for r in personal.recipes if r.uid in personal.required},database_limits={},enabled_databases=['personal'])
    app.week=plan(personal.recipes,require_nutrition=False,seed=42,required_ids=context['required_ids'],wanted=context['wanted'])
    app.last_plan_settings=context;app.render_week();app.tabs.select(app.menu_tab);app.update()
    capture(app,'09-menu.png',[variable(app,app.menu_day),app.day_recipes,button(app,'Редактировать рецепт на весь экран'),
        button(app,'Пересчитать после правок'),button(app,'Заменить блюдо…'),button(app,'Перенести / обменять…'),app.undo_button])
    replace=ReplaceDialog(app,(0,0));replace.geometry('+150+60');replace.update()
    match=next((r for r in replace.matches if r.uid!=app.week[0][0].uid),replace.matches[0])
    replace.tree.selection_set(recipe_key(match));replace.show_preview();replace.update()
    capture(replace,'10-replace.png',[variable(replace,replace.database),variable(replace,replace.query),replace.tree,replace.preview,replace.apply_button]);replace.destroy()
    move=MoveDialog(app,(0,0));move.geometry('+220+150');move.day.set('День 2');move.meal.set('Утро · завтрак');move.update()
    capture(move,'11-move.png',[variable(move,move.day),variable(move,move.meal),button(move,'Обменять местами — изменятся только две позиции'),
        button(move,'Перенести со сдвигом — промежуточные блюда сдвинутся на одну позицию'),button(move,'Применить и пересчитать')]);move.destroy()
    app.tabs.select(app.result_tab);app.update()
    capture(app,'12-report.png',[app.export_button,app.recalculate_button,app.replan_button,button(app,'← Изменить цели'),app.output])
    preview_context={**context,'require_nutrition':True,'fat':30,'nutrition_mode':'weekly'}
    def save_preview():
        dialog=next(w for w in app.winfo_children() if isinstance(w,tk.Toplevel));dialog.geometry('+170+70');dialog.update()
        text=next(w for w in walk(dialog) if w.winfo_class()=='Text')
        capture(dialog,'13-deviations.png',[text,button(dialog,'Принять меню с этими отклонениями'),button(dialog,'Отмена — сохранить текущее меню')])
        dialog.destroy()
    app.after(100,save_preview)
    app.confirm_nutrition_preview(app.week,preview_context,'Учебный пример: не найден вариант с заданной целью жиров.')
    app.destroy()
print('Saved 13 real UI screenshots to',OUT)
