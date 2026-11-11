"""Family meal planner: guided local desktop UI, standard Python/Tk only."""
import copy
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from tkinter.scrolledtext import ScrolledText
import webbrowser
import uuid
from diagnostics import APP_VERSION,configure_logging,close_logging,log_plan
from core import Recipe, Ingredient, MEALS, validate_recipe, readiness, plan, NutritionSearchFailure, refresh_week, recipe_key
from nutrition import KEYS, DEFAULT_TARGETS, FOODS, normalize, number, ingredient_nutrition, recipe_nutrition, nutrition_text, reference_food, ingredient_amount
from estimation import servings_info
from tagging import TAGS, recipe_tags
from catalog import search_foods
from importing import import_url, public_url, parse_ingredient, import_docx, import_html
from storage import load_library, save_library, save_json
from menu_editing import arrangement_warnings
from menu_dialogs import ReplaceDialog,MoveDialog
from databases import DatabaseManager
from reports import week_report, day_recipe_text, week_issues, balance_options
from examples import example_recipes

DATA = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'NJ-cooking' / 'recipes.json'
FONT = 'Segoe UI' if os.name == 'nt' else 'Noto Sans'
NUTRIENT_LABELS = ('Калории, ккал', 'Белки, г', 'Жиры, г', 'Углеводы, г')


def entry_row(parent, label, variable, row, column=0, width=24):
    ttk.Label(parent, text=label).grid(row=row, column=column, sticky='w', padx=5, pady=(5, 2))
    result = ttk.Entry(parent, textvariable=variable, width=width)
    result.grid(row=row+1, column=column, sticky='ew', padx=5, pady=(0, 5))
    return result


class IngredientDialog(tk.Toplevel):
    def __init__(self, parent, ingredient=None):
        super().__init__(parent)
        self.title('Продукт в рецепте')
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        i = ingredient or Ingredient('', None, 'г')
        frame = ttk.Frame(self, padding=15)
        frame.pack(fill='both', expand=True)
        self.original_ingredient=copy.deepcopy(i)
        self.fdc_id=i.fdc_id
        self.reference_name=normalize(i.name)
        self.keep_estimate=tk.BooleanVar(value=i.amount_estimate is not None)
        self.name = tk.StringVar(value=i.name)
        self.amount = tk.StringVar(value='' if i.amount is None else f'{i.amount:g}')
        self.unit = tk.StringVar(value=i.unit or 'г')
        entry_row(frame, 'Название продукта', self.name, 0, width=42)
        entry_row(frame, 'Количество во всём исходном рецепте', self.amount, 2)
        ttk.Label(frame, text='Единица').grid(row=4, column=0, sticky='w', padx=5)
        ttk.Combobox(frame, textvariable=self.unit, values=('г', 'кг', 'мл', 'л', 'шт', 'ст. л.', 'ч. л.', 'cup'), width=40).grid(row=5, column=0, padx=5, pady=5, sticky='ew')
        ttk.Label(frame, text='Не знаете количество? Оставьте пустым и сохраните черновик.', wraplength=400).grid(row=6, column=0, sticky='w', padx=5, pady=5)
        self.hint = ttk.Label(frame, text='', wraplength=410)
        self.hint.grid(row=7, column=0, padx=5, pady=5, sticky='w')
        self.name.trace_add('write', lambda *_: self.name_changed())
        self.reference_hint()
        ttk.Button(frame,text='Выбрать продукт из полной базы USDA…',command=self.choose_usda).grid(row=7,column=1,sticky='e',padx=8)
        if i.amount_estimate is not None:
            ttk.Checkbutton(frame,text=f'Использовать оценку количества ≈ {i.amount_estimate:g}',variable=self.keep_estimate).grid(row=6,column=1,sticky='w')
        box = ttk.LabelFrame(frame, text='Необязательно: своё КБЖУ на 100 г', padding=8)
        box.grid(row=8, column=0, sticky='ew', pady=5)
        self.values = [tk.StringVar(value='' if i.per100g is None else f'{i.per100g[n]:g}') for n in range(4)]
        for n, (label, var) in enumerate(zip(NUTRIENT_LABELS, self.values)):
            entry_row(box,label,var,(n//2)*2,n%2,width=18)
        self.mass = tk.StringVar(value='' if i.grams_per_unit is None else f'{i.grams_per_unit:g}')
        entry_row(frame, 'Для шт — грамм/шт; для мл и л — грамм/мл', self.mass, 9)
        self.error = ttk.Label(frame, foreground='#a4262c', wraplength=410)
        self.error.grid(row=11, column=0, sticky='w', padx=5)
        actions = ttk.Frame(frame)
        actions.grid(row=12, column=0, sticky='e', pady=10)
        ttk.Button(actions, text='Отмена', command=self.destroy).pack(side='left', padx=5)
        ttk.Button(actions, text='Готово', command=self.save).pack(side='left')
        self.bind('<Escape>', lambda _: self.destroy())
        self.grab_set()

    def reference_hint(self):
        food=reference_food(self.name.get(),self.fdc_id)
        text = ('Есть в справочнике: ' + nutrition_text(dict(zip(KEYS, food.values))) + ' на 100 г. Значения приблизительные.' if food else
                'Нет точного совпадения в справочнике. Можно задать КБЖУ продукта ниже или КБЖУ всего блюда в карточке рецепта.')
        if food and food.fdc_id:
            text += f' FDC {food.fdc_id}: {food.description}.'
        if food and food.piece_g:
            text += f' Принято: 1 шт ≈ {food.piece_g:g} г; массу можно изменить ниже.'
        if food and food.density:
            text += f' Принято: 1 мл ≈ {food.density:g} г.'
        self.hint.config(text=text)

    def name_changed(self):
        if normalize(self.name.get())!=self.reference_name:self.fdc_id=None
        self.reference_hint()

    def choose_usda(self):
        dialog=tk.Toplevel(self)
        dialog.title('Справочник USDA — выбор продукта')
        dialog.transient(self)
        dialog.geometry('850x500')
        query=tk.StringVar(value=self.name.get())
        ttk.Label(dialog,text='Поиск по русским алиасам, английскому описанию или FDC ID. Выбирайте raw/cooked и жирность внимательно.',wraplength=800,padding=10).pack(anchor='w')
        ttk.Entry(dialog,textvariable=query).pack(fill='x',padx=10)
        tree=ttk.Treeview(dialog,columns=('dataset',),show='tree headings',selectmode='browse')
        tree.heading('#0',text='USDA продукт — КБЖУ на 100 г')
        tree.heading('dataset',text='Источник')
        tree.column('#0',width=620)
        tree.column('dataset',width=120)
        tree.pack(fill='both',expand=True,padx=10,pady=10)
        def search():
            tree.delete(*tree.get_children())
            for row in search_foods(query.get()):
                values=dict(zip(KEYS,row['values']))
                tree.insert('','end',iid=str(row['id']),text=f"{row['id']} · {row['description']} · {nutrition_text(values)}",values=(row['dataset'],))
        def choose():
            selected=tree.selection()
            if selected:
                self.fdc_id=int(selected[0]);self.reference_name=normalize(self.name.get())
                self.reference_hint();dialog.destroy();self.grab_set()
        toolbar=ttk.Frame(dialog);toolbar.pack(fill='x',padx=10,pady=10)
        ttk.Button(toolbar,text='Найти',command=search).pack(side='left')
        ttk.Button(toolbar,text='Использовать выбранный',command=choose).pack(side='right')
        dialog.bind('<Return>',lambda _:search())
        tree.bind('<Double-1>',lambda _:choose())
        search();dialog.grab_set()

    def save(self):
        try:
            name = self.name.get().strip()
            if not name:
                raise ValueError('Введите название продукта.')
            values = [number(v.get(), label) for v, label in zip(self.values, NUTRIENT_LABELS)]
            if any(v is not None for v in values) and any(v is None for v in values):
                raise ValueError('Заполните все четыре значения на 100 г либо оставьте все пустыми.')
            self.result = Ingredient(name, number(self.amount.get(), 'Количество', allow_zero=False), self.unit.get().strip(),
                                     values if all(v is not None for v in values) else None,
                                     number(self.mass.get(), 'Масса единицы', allow_zero=False),
                                     original=self.original_ingredient.original,fdc_id=self.fdc_id,
                                     amount_estimate=self.original_ingredient.amount_estimate if self.keep_estimate.get() else None,
                                     amount_basis=self.original_ingredient.amount_basis if self.keep_estimate.get() else '')
            self.destroy()
        except ValueError as exc:
            self.error.config(text=str(exc))


class App(tk.Tk):
    def __init__(self, data_path=DATA, include_bundled=None):
        super().__init__()
        self.title(f'Семейное меню {APP_VERSION} • рецепты, КБЖУ и покупки')
        self.geometry('1240x860')
        self.minsize(1000, 700)
        self.data_path = Path(data_path)
        self.logger,self.log_path=configure_logging(self.data_path.parent/'logs')
        self.logger.info('Tk=%s data_directory=%s',tk.TkVersion,self.data_path.parent)
        self.include_bundled = (self.data_path == DATA) if include_bundled is None else include_bundled
        self.settings_path = self.data_path.with_name('settings.json')
        self.menu_path = self.data_path.with_name('menu.json')
        self.last_plan_settings = None
        self.editor_uid = None
        self.search_timer = None
        self.manager=None
        self.browse_database="personal"
        self.library_page=0
        self.editor_database_id="personal"
        self.editor_expanded=False
        self.recipes = []
        self.current = None
        self.ingredients_data = []
        self.loaded_notes = []
        self.loaded_source_metadata={}
        self.menu_history=[]
        self.baseline = None
        self.busy = False
        self.selection_lock = False
        self.events = queue.Queue()
        self.report = ''
        self.week = None
        self.import_button = None
        style = ttk.Style(self)
        if os.name == 'nt':
            style.theme_use('vista' if 'vista' in style.theme_names() else 'clam')
        else:
            style.theme_use('clam')
        style.configure('.', font=(FONT, 10))
        style.configure('Treeview', rowheight=28)
        style.configure('TButton', padding=(10, 6))
        style.configure('Title.TLabel', font=(FONT, 18, 'bold'))
        style.configure('Subtitle.TLabel', font=(FONT, 10), foreground='#4b5563')
        style.configure('Primary.TButton', padding=(16, 8))
        self.option_add('*Font', (FONT, 10))
        header = ttk.Frame(self, padding=(18, 12))
        header.pack(fill='x')
        ttk.Button(header,text='Журнал ошибок…',command=self.show_log_location).pack(side='right')
        ttk.Label(header, text=f'Семейное меню {APP_VERSION}', style='Title.TLabel').pack(anchor='w')
        ttk.Label(header, text='1. Базы и обязательные рецепты → 2. Настройки → 3. Покупки и КБЖУ → 4. Меню по дням', style='Subtitle.TLabel').pack(anchor='w', pady=(4, 0))
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=15)
        self.library_tab, self.settings_tab, self.result_tab, self.menu_tab = [ttk.Frame(self.tabs, padding=12) for _ in range(4)]
        for frame, title in zip((self.library_tab, self.settings_tab, self.result_tab, self.menu_tab), ('1. Базы и рецепты', '2. Семья и цели КБЖУ', '3. Итоги и покупки', '4. Меню')):
            self.tabs.add(frame, text=title)
        self.status = tk.StringVar(value='Начните с кнопки «Новый рецепт», «Из ссылки» или «Примеры».')
        ttk.Label(self, textvariable=self.status, padding=(18, 10), wraplength=1100).pack(fill='x')
        self.build_library()
        self.build_settings()
        self.build_result()
        self.build_day_menu()
        self.status.set('Подключаю базы и переношу прежние данные…')
        self.update_idletasks()
        try:
            self.manager=DatabaseManager(self.data_path,self.include_bundled)
            self.recipes=self.manager.all_recipes()
            self.update_database_choices()
        except (ValueError,OSError,KeyError,TypeError) as exc:
            self.logger.exception('database_startup_failed')
            messagebox.showerror('Рецепты не загружены — данные сохранены', str(exc), parent=self)
            self.after_idle(self.destroy)
            return
        self.load_settings()
        self.refresh_library()
        self.load_editor(None)
        self.load_saved_week()
        if self.include_bundled:self.status.set(f"Подключено баз: {len(self.manager.databases)} · Рецептов: {len(self.recipes)}. Для подбора используются только включённые БД.")
        self.poll_id = self.after(80, self.poll_events)
        self.protocol('WM_DELETE_WINDOW', self.close)

    def build_library(self):
        dbbar=ttk.Frame(self.library_tab)
        dbbar.pack(fill='x',pady=(0,8))
        ttk.Label(dbbar,text='Открытая база:').pack(side='left')
        self.database_choice=tk.StringVar()
        self.database_combo=ttk.Combobox(dbbar,textvariable=self.database_choice,state='readonly',width=24)
        self.database_combo.pack(side='left',padx=6)
        self.database_combo.bind('<<ComboboxSelected>>',self.change_database)
        self.database_enabled=tk.BooleanVar(value=True)
        ttk.Checkbutton(dbbar,text='Использовать эту БД для меню',variable=self.database_enabled,command=self.save_database_options).pack(side='left',padx=6)
        ttk.Button(dbbar,text='Подключить JSON…',command=self.connect_database).pack(side='left',padx=4)
        ttk.Button(dbbar,text='Создать БД…',command=self.create_database).pack(side='left')
        limits=ttk.Frame(self.library_tab)
        limits.pack(fill='x',pady=(0,8))
        ttk.Label(limits,text='Блюд из этой БД за неделю (0–21, пусто — свободно):').pack(side='left')
        self.database_quota=tk.StringVar()
        quota=ttk.Entry(limits,textvariable=self.database_quota,width=5)
        quota.pack(side='left',padx=6)
        quota.bind('<FocusOut>',lambda _:self.save_database_options())
        quota.bind('<Return>',lambda _:self.save_database_options())
        self.database_summary=ttk.Label(limits,wraplength=650)
        self.database_summary.pack(side='left',padx=8)
        split = ttk.Panedwindow(self.library_tab, orient='horizontal')
        split.pack(fill='both', expand=True)
        left = ttk.Frame(split, width=330)
        right = ttk.Frame(split)
        self.library_split=split
        self.library_left=left
        self.library_right=right
        split.add(left, weight=1)
        split.add(right, weight=3)
        toolbar = ttk.Frame(left)
        toolbar.pack(fill='x', pady=(0, 8))
        ttk.Button(toolbar, text='+ Новый', command=self.new_recipe).pack(side='left')
        ttk.Button(toolbar, text='Из ссылки', command=self.url_dialog).pack(side='left', padx=3)
        ttk.Button(toolbar, text='Word', command=self.import_word).pack(side='left')
        ttk.Button(toolbar,text='HTML',command=self.import_saved_html).pack(side='left',padx=3)
        self.search = tk.StringVar()
        ttk.Label(left, text='Найти рецепт').pack(anchor='w')
        ttk.Entry(left, textvariable=self.search).pack(fill='x', pady=5)
        self.search.trace_add('write', lambda *_: self.schedule_search())
        self.only_required=tk.BooleanVar(value=False)
        ttk.Checkbutton(left,text='Только обязательные рецепты',variable=self.only_required,command=self.reset_library_page).pack(anchor='w')
        footer=ttk.Frame(left)
        footer.pack(side='bottom',fill='x')
        tree_area=ttk.Frame(left)
        tree_area.pack(fill='both',expand=True)
        self.library = ttk.Treeview(tree_area, columns=('required','state'), show='tree headings', selectmode='browse', height=14)
        self.library.heading('#0', text='Название')
        self.library.heading('required',text='В меню')
        self.library.column('required',width=65,stretch=False)
        self.library.heading('state', text='Статус')
        self.library.column('#0', width=190)
        self.library.column('state', width=110)
        scroll = ttk.Scrollbar(tree_area, orient='vertical', command=self.library.yview)
        self.library.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.library.pack(fill='both', expand=True)
        self.library.bind('<<TreeviewSelect>>', self.select_recipe)
        self.library.bind('<Button-1>',self.click_required)
        self.library.bind('<space>',self.space_required)
        pages=ttk.Frame(footer);pages.pack(fill='x',pady=4)
        ttk.Button(pages,text='← Назад',command=lambda:self.page_library(-1)).pack(side='left')
        ttk.Button(pages,text='Далее →',command=lambda:self.page_library(1)).pack(side='left',padx=4)
        ttk.Button(pages,text='Сбросить поиск',command=self.reset_search).pack(side='left')
        ttk.Button(footer,text='Сбросить избранное этой БД…',command=self.reset_required).pack(fill='x',pady=4)
        self.library_count = ttk.Label(footer, wraplength=310)
        self.library_count.pack(anchor='w', pady=8)
        actions = ttk.Frame(footer)
        actions.pack(fill='x')
        ttk.Button(actions, text='Примеры', command=self.add_examples).pack(side='left')
        ttk.Button(actions, text='Удалить', command=self.delete_recipe).pack(side='left', padx=4)
        ttk.Button(footer, text='Далее: семья и цели →', command=lambda: self.tabs.select(self.settings_tab)).pack(fill='x', pady=10)
        fixed_actions = ttk.Frame(right, padding=(15, 0, 8, 8))
        fixed_actions.pack(fill='x')
        ttk.Button(fixed_actions, text='Сохранить изменения рецепта', style='Primary.TButton', command=self.save_recipe).pack(side='left')
        self.expand_button=ttk.Button(fixed_actions,text='Развернуть карточку',command=self.toggle_editor)
        self.expand_button.pack(side='left',padx=6)
        self.bind('<Control-s>', lambda _: self.save_recipe() if self.tabs.select() == str(self.library_tab) else None)
        # Scrollable editor keeps the form accessible on smaller Windows screens.
        canvas = tk.Canvas(right, highlightthickness=0)
        scrollbar = ttk.Scrollbar(right, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        form = ttk.Frame(canvas, padding=(15, 0, 8, 12))
        window = canvas.create_window((0, 0), window=form, anchor='nw')
        form.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        def wheel(event):
            widget = self.winfo_containing(event.x_root, event.y_root)
            while widget is not None:
                if widget is form:
                    canvas.yview_scroll(-int(event.delta / 120) if event.delta else 0, 'units')
                    break
                widget = getattr(widget, 'master', None)
        self.bind_all('<MouseWheel>', wheel, add='+')
        self.editor_title = ttk.Label(form, text='Новый рецепт', font=(FONT, 14, 'bold'))
        self.editor_title.pack(anchor='w')
        ttk.Label(form, text='Неполный рецепт можно сохранить. Для меню нужен известный или оценённый выход. Полное КБЖУ требуется только при включённой проверке.', wraplength=650).pack(anchor='w', pady=5)
        self.fields = {key: tk.StringVar() for key in ('name', 'servings', 'kcal', 'protein', 'fat', 'carbs', 'source_url', 'meal')}
        basic = ttk.Frame(form)
        basic.pack(fill='x')
        basic.columnconfigure(0, weight=3)
        basic.columnconfigure(1, weight=1)
        entry_row(basic, 'Название *', self.fields['name'], 0)
        entry_row(basic, 'Исходное число порций', self.fields['servings'], 0, 1)
        ttk.Label(basic, text='Подходит для').grid(row=2, column=0, sticky='w', padx=5)
        ttk.Combobox(basic, textvariable=self.fields['meal'], values=('Любой', *MEALS), state='readonly').grid(row=3, column=0, sticky='ew', padx=5, pady=5)
        nutrition = ttk.LabelFrame(form, text='КБЖУ НА ОДНУ ПОРЦИЮ — поля можно оставить пустыми', padding=8)
        nutrition.pack(fill='x', pady=8)
        for n, (key, label) in enumerate(zip(KEYS, NUTRIENT_LABELS)):
            nutrition.columnconfigure(n, weight=1)
            entry_row(nutrition, label, self.fields[key], 0, n, width=12)
        ttk.Label(nutrition, text='Пустое поле = расчёт по ингредиентам. Ручное число — НА ОДНУ ПОРЦИЮ; при смене исходного выхода проверьте его. Ноль означает 0.', wraplength=650).grid(row=2, column=0, columnspan=4, sticky='w', pady=5)
        self.nutrition_preview = ttk.Label(nutrition, wraplength=650)
        self.nutrition_preview.grid(row=3, column=0, columnspan=4, sticky='w')
        tags_box = ttk.LabelFrame(form, text='Принадлежность блюда — можно отметить несколько', padding=8)
        tags_box.pack(fill='x', pady=5)
        self.recipe_tag_vars = {tag: tk.BooleanVar(value=False) for tag in TAGS}
        for n,(tag,var) in enumerate(self.recipe_tag_vars.items()):
            ttk.Checkbutton(tags_box,text=tag,variable=var,command=self.update_preview).grid(row=n//3,column=n%3,sticky='w',padx=4)
        ttk.Button(tags_box,text='Определить по названию и составу',command=self.auto_tags).grid(row=5,column=0,columnspan=3,sticky='w',pady=5)
        self.ingredients_tree = ttk.Treeview(form, columns=('amount', 'unit'), show='tree headings', height=6, selectmode='browse')
        for key, text, width in (('#0', 'Продукты во всём исходном рецепте', 310), ('amount', 'Количество', 110), ('unit', 'Ед.', 80)):
            self.ingredients_tree.heading(key, text=text)
            self.ingredients_tree.column(key, width=width)
        self.ingredients_tree.pack(fill='x')
        self.ingredients_tree.bind('<Double-1>', lambda _: self.edit_ingredient())
        ingredients_bar = ttk.Frame(form)
        ingredients_bar.pack(fill='x', pady=5)
        for text, command in (('+ Продукт', self.add_ingredient), ('Изменить', self.edit_ingredient), ('Удалить', self.remove_ingredient), ('Вставить список', self.paste_ingredients)):
            ttk.Button(ingredients_bar, text=text, command=command).pack(side='left', padx=(0, 4))
        ttk.Label(form, text='Приготовление').pack(anchor='w')
        self.method = ScrolledText(form, height=6, wrap='word', undo=True)
        self.method.pack(fill='x', pady=5)
        source = ttk.Frame(form)
        source.pack(fill='x')
        source.columnconfigure(0, weight=1)
        entry_row(source, 'Ссылка на источник (фото и видео остаются на сайте)', self.fields['source_url'], 0, width=50)
        ttk.Button(source, text='Открыть источник ↗', command=self.open_source).grid(row=1, column=1, padx=5)
        self.notes = ttk.Label(form, wraplength=650, foreground='#665000')
        self.notes.pack(anchor='w', pady=5)
        self.editor_message = ttk.Label(form, wraplength=650)
        self.editor_message.pack(anchor='w', pady=5)
        ttk.Button(form, text='Сохранить изменения рецепта', style='Primary.TButton', command=self.save_recipe).pack(anchor='w', pady=8)
        for var in self.fields.values():
            var.trace_add('write', lambda *_: self.update_preview())

    def build_settings(self):
        footer = ttk.Frame(self.settings_tab)
        footer.pack(side='bottom', fill='x', pady=(8, 0))
        self.plan_message = ttk.Label(footer, wraplength=1000)
        self.plan_message.pack(anchor='w', pady=5)
        self.generate_button = ttk.Button(footer, text='Составить меню на неделю →', style='Primary.TButton', command=self.generate)
        self.generate_button.pack(anchor='w')
        canvas = tk.Canvas(self.settings_tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.settings_tab, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        content = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        def wheel(event):
            widget = self.winfo_containing(event.x_root, event.y_root)
            while widget is not None:
                if widget is content:
                    canvas.yview_scroll(-int(event.delta / 120) if event.delta else 0, 'units')
                    break
                widget = getattr(widget, 'master', None)
        self.bind_all('<MouseWheel>', wheel, add='+')
        ttk.Label(content, text='Настройте меню для семьи', font=(FONT, 15, 'bold')).pack(anchor='w')
        ttk.Label(content, text='Три приёма пищи в день. Все цели КБЖУ — на одного человека в сутки; продукты рассчитываются на всю семью.', wraplength=1000).pack(anchor='w', pady=8)
        self.settings = {key: tk.StringVar(value=value) for key, value in {
            'people': '2', 'portions': '1', 'kcal': '2000', 'protein': '75', 'fat': '67', 'carbs': '275',
            'tolerance': '200', 'macro_tolerance': '20', 'daily_kcal_spread':'30', 'daily_macro_spread':'50', 'protein_floor':'75', 'excluded': '', 'wanted': ''}.items()}
        family = ttk.LabelFrame(content, text='Семья', padding=12)
        family.pack(fill='x', pady=8)
        entry_row(family, 'Количество человек', self.settings['people'], 0)
        entry_row(family, 'Порций на человека за один приём пищи', self.settings['portions'], 0, 1, width=36)
        box = ttk.LabelFrame(content, text='Желаемое КБЖУ на человека в сутки', padding=12)
        box.pack(fill='x', pady=8)
        for n, (key, label) in enumerate(zip(KEYS, NUTRIENT_LABELS)):
            entry_row(box, label, self.settings[key], 0, n, width=16)
        entry_row(box, 'Допуск калорий ± ккал', self.settings['tolerance'], 2, 0)
        entry_row(box, 'Допуск Б, Ж и У ± %', self.settings['macro_tolerance'], 2, 1)
        ttk.Button(box, text='Вернуть стартовые значения', command=self.reset_targets).grid(row=3, column=2, columnspan=2, padx=5)
        ttk.Label(box, text='Если поле пустое, используется: 2000 ккал, Б 75 г, Ж 67 г, У 275 г; допуски ±200 ккал и ±20% БЖУ.\nЭто стартовый ориентир для взрослого, а не индивидуальная норма. Для детей и разных потребностей измените цели.', wraplength=1000).grid(row=4, column=0, columnspan=4, sticky='w', padx=5, pady=8)
        self.require_nutrition=tk.BooleanVar(value=False)
        ttk.Checkbutton(box,text='Обязательный контроль КБЖУ — полные данные и соблюдение выбранного режима',variable=self.require_nutrition).grid(row=5,column=0,columnspan=4,sticky='w',pady=5)
        ttk.Label(box,text='Без отметки: неизвестное КБЖУ не блокирует подбор, цели — пожелание. Выход блюда должен быть указан или оценён.',wraplength=1000).grid(row=6,column=0,columnspan=4,sticky='w')
        mode_box=ttk.LabelFrame(content,text='Баланс КБЖУ',padding=12)
        mode_box.pack(fill='x',pady=8)
        self.nutrition_mode=tk.StringVar(value='Недельный баланс')
        ttk.Combobox(mode_box,textvariable=self.nutrition_mode,values=('Недельный баланс','Строгий дневной'),state='readonly',width=28).grid(row=0,column=0,sticky='w')
        ttk.Label(mode_box,text='Недельный: среднее за 7 дней в пределах цели; каждый день — ближе к ориентиру, без больших перекосов.\nДневной: все четыре показателя в пределах цели ежедневно. При выключенном контроле цели остаются пожеланиями.',wraplength=950).grid(row=1,column=0,columnspan=3,sticky='w',pady=8)
        entry_row(mode_box,'Дневной разброс калорий ± %',self.settings['daily_kcal_spread'],2,0)
        entry_row(mode_box,'Дневной разброс БЖУ ± %',self.settings['daily_macro_spread'],2,1)
        entry_row(mode_box,'Минимум белка за день, % цели',self.settings['protein_floor'],2,2)
        ttk.Label(mode_box,text='Дневные границы применяются в недельном режиме. Старт: калории ±30%, БЖУ ±50%, белок не ниже 75% цели. Это настраиваемые границы подбора, не медицинские нормы.',wraplength=950).grid(row=4,column=0,columnspan=3,sticky='w',pady=8)
        tag_box=ttk.LabelFrame(content,text='Желаемые блюда — разрешить любой из отмеченных типов',padding=10)
        tag_box.pack(fill='x',pady=8)
        self.desired_tag_vars={tag:tk.BooleanVar(value=False) for tag in TAGS}
        for n,(tag,var) in enumerate(self.desired_tag_vars.items()):
            ttk.Checkbutton(tag_box,text=tag,variable=var).grid(row=n//4,column=n%4,sticky='w',padx=8)
        ttk.Label(tag_box,text='Нет отметок — все типы. Фильтр действует на автоматический подбор; обязательные рецепты включаются независимо от типов.',wraplength=1000).grid(row=4,column=0,columnspan=4,sticky='w',pady=5)
        restrictions = ttk.LabelFrame(content, text='Продукты', padding=12)
        restrictions.pack(fill='x', pady=8)
        restrictions.columnconfigure(0, weight=1)
        entry_row(restrictions, 'Исключить (через запятую)', self.settings['excluded'], 0, width=80)
        entry_row(restrictions, 'Использовать остатки: каждый продукт хотя бы раз за неделю (через запятую)', self.settings['wanted'], 2, width=80)
        ttk.Label(restrictions, text='Сопоставление по части названия: «молок» найдёт «молоко». Количество остатков пока не учитывается.', wraplength=1000).grid(row=4, column=0, sticky='w', padx=5, pady=5)

    def build_result(self):
        actions=ttk.Frame(self.result_tab)
        actions.pack(fill='x',pady=(0,6))
        ttk.Button(actions,text='← Изменить цели',command=lambda:self.tabs.select(self.settings_tab)).pack(side='left')
        self.export_button=ttk.Button(actions,text='Сохранить меню (.txt)',command=self.export,state='disabled')
        self.export_button.pack(side='left',padx=6)
        self.recalculate_button=ttk.Button(actions,text='Пересчитать эти блюда',command=self.recalculate_week,state='disabled')
        self.recalculate_button.pack(side='left',padx=6)
        self.replan_button=ttk.Button(actions,text='Подобрать заново из этих блюд',command=self.replan_current,state='disabled')
        self.replan_button.pack(side='left')
        self.week_message=tk.StringVar(value='После подбора: двойной щелчок по блюду → правки → сохранить → пересчитать или подобрать заново.')
        ttk.Label(self.result_tab,textvariable=self.week_message,wraplength=1050).pack(anchor='w',pady=5)
        ttk.Button(self.result_tab,text='Открыть выбранный рецепт для правки',command=self.edit_week_recipe).pack(anchor='w',pady=(0,5))
        week_list=ttk.Frame(self.result_tab)
        week_list.pack(fill='x')
        self.week_tree=ttk.Treeview(week_list,columns=('meal',),show='tree headings',height=5,selectmode='browse')
        self.week_tree.heading('#0',text='21 блюдо · день и рецепт (двойной щелчок — изменить)')
        self.week_tree.heading('meal',text='Приём пищи')
        self.week_tree.column('#0',width=720)
        self.week_tree.column('meal',width=140)
        week_scroll=ttk.Scrollbar(week_list,orient='vertical',command=self.week_tree.yview)
        self.week_tree.configure(yscrollcommand=week_scroll.set)
        week_scroll.pack(side='right',fill='y')
        self.week_tree.pack(side='left',fill='x',expand=True)
        # Mouse-wheel and keyboard navigation work for all 21 entries.
        self.week_tree.bind('<Double-1>',lambda _:self.edit_week_recipe())
        self.output=ScrolledText(self.result_tab,wrap='word',state='disabled',font=(FONT,10))
        self.output.pack(fill='both',expand=True,pady=(6,0))
        self.set_output('Встроенные рецепты уже доступны на шаге 1. Настройте семью, теги и контроль КБЖУ на шаге 2 и составьте меню.')

    def build_day_menu(self):
        bar=ttk.Frame(self.menu_tab);bar.pack(fill='x',pady=(0,8))
        ttk.Label(bar,text='Выберите день:').pack(side='left')
        self.menu_day=tk.StringVar(value='День 1')
        ttk.Combobox(bar,textvariable=self.menu_day,values=[f'День {n}' for n in range(1,8)],state='readonly',width=15).pack(side='left',padx=10)
        self.menu_day.trace_add('write',lambda *_:self.render_day_menu())
        ttk.Button(bar,text='Редактировать рецепт на весь экран',command=self.edit_day_recipe).pack(side='left',padx=6)
        ttk.Button(bar,text='Пересчитать после правок',command=self.recalculate_week).pack(side='left')
        edits=ttk.Frame(self.menu_tab);edits.pack(fill='x',pady=(0,6))
        ttk.Button(edits,text='Заменить блюдо…',command=self.replace_menu_dialog).pack(side='left')
        ttk.Button(edits,text='Перенести / обменять…',command=self.move_menu_dialog).pack(side='left',padx=8)
        self.undo_button=ttk.Button(edits,text='Отменить изменение',command=self.undo_menu_change,state='disabled')
        self.undo_button.pack(side='left')
        ttk.Label(self.menu_tab,textvariable=self.week_message,wraplength=1100).pack(anchor='w',pady=5)
        self.day_summary=ttk.Label(self.menu_tab,font=(FONT,11,'bold'),wraplength=1100)
        self.day_summary.pack(anchor='w',pady=5)
        self.day_recipes=ttk.Treeview(self.menu_tab,columns=('meal',),show='tree headings',height=3,selectmode='browse')
        self.day_recipes.heading('#0',text='Рецепты выбранного дня — выберите для просмотра')
        self.day_recipes.heading('meal',text='Приём пищи')
        self.day_recipes.column('#0',width=800);self.day_recipes.column('meal',width=150)
        self.day_recipes.pack(fill='x',pady=6)
        self.day_recipes.bind('<<TreeviewSelect>>',lambda _:self.show_day_recipe())
        self.day_reader=ScrolledText(self.menu_tab,wrap='word',font=(FONT,11),state='disabled',padx=15,pady=12)
        self.day_reader.pack(fill='both',expand=True)
        self.set_reader_text(self.day_reader,'Составьте неделю на шаге 2. Здесь появятся рецепты по дням с большим окном приготовления.')

    def day_index(self):
        try:return max(0,min(6,int(self.menu_day.get().split()[-1])-1))
        except (ValueError,IndexError):return 0

    def render_day_menu(self):
        if not hasattr(self,'day_recipes'):return
        selected=self.day_recipes.selection()
        previous=selected[0] if selected else '0'
        self.day_recipes.delete(*self.day_recipes.get_children())
        if not self.week:
            self.day_summary.config(text='Меню ещё не составлено.');return
        d=self.day_index()
        from nutrition import nutrition_totals
        c=self.last_plan_settings
        self.day_summary.config(text=f'День {d+1} · КБЖУ на человека: '+nutrition_text(nutrition_totals([(r,c['portions']) for r in self.week[d]])))
        for m,r in enumerate(self.week[d]):self.day_recipes.insert('','end',iid=str(m),text=r.name,values=(MEALS[m],))
        self.day_recipes.selection_set(previous if self.day_recipes.exists(previous) else '0')
        self.show_day_recipe()

    def show_day_recipe(self):
        selected=self.day_recipes.selection()
        if not self.week or not selected:return
        recipe=self.week[self.day_index()][int(selected[0])]
        c=self.last_plan_settings
        name=self.manager.get(recipe.database_id).name
        self.set_reader_text(self.day_reader,'База: '+name+'\n\n'+day_recipe_text(recipe,c['people'],c['portions']))

    def edit_day_recipe(self):
        if not self.week or not self.day_recipes.selection():
            self.status.set('Сначала составьте меню и выберите рецепт дня.');return
        if not self.confirm_switch():return
        self.open_recipe_editor(self.week[self.day_index()][int(self.day_recipes.selection()[0])])

    def selected_menu_slot(self):
        if not self.week or not self.day_recipes.selection():
            self.status.set('Выберите блюдо на вкладке «4. Меню».');return None
        return self.day_index(),int(self.day_recipes.selection()[0])

    def replace_menu_dialog(self):
        if self.busy or not self.confirm_switch():return
        slot=self.selected_menu_slot()
        if slot is not None:ReplaceDialog(self,slot)

    def move_menu_dialog(self):
        if self.busy or not self.confirm_switch():return
        slot=self.selected_menu_slot()
        if slot is not None:MoveDialog(self,slot)

    def menu_change_warnings(self,week):
        from reports import week_issues
        c=dict(self.last_plan_settings)
        names=dict(c.get('required_names',{}))
        names.update({recipe_key(r):r.name for r in self.recipes})
        c['required_names']=names
        c['database_names']={d.uid:d.name for d in self.manager.databases}
        extra=arrangement_warnings(week,c,{d.uid for d in self.manager.databases if d.enabled})
        extra+=week_issues(week,c['portions'],{k:c[k] for k in KEYS},c['tolerance'],c['macro_tolerance'],**balance_options(c))
        return extra

    def apply_menu_change(self,new_week,action,select=None):
        if self.busy or not self.week:return False
        previous=self.week
        selected=self.selected_menu_slot() or (0,0)
        try:
            new_week=refresh_week(new_week,self.recipes)
            if [[recipe_key(r) for r in d] for d in new_week]==[[recipe_key(r) for r in d] for d in previous]:
                self.status.set('Расположение блюд не изменилось.');return True
            self.week=new_week
            self.render_week()  # Saves before updating widgets; a write failure leaves the old UI intact.
        except (ValueError,OSError) as exc:
            self.week=previous
            self.logger.exception('manual_menu_change_failed action=%s',action)
            messagebox.showerror('Изменение меню не сохранено',str(exc),parent=self)
            return False
        self.menu_history.append((previous,selected));self.menu_history=self.menu_history[-20:]
        self.undo_button.config(state='normal')
        target=select or selected
        self.menu_day.set(f'День {target[0]+1}')
        self.day_recipes.selection_set(str(target[1]));self.show_day_recipe()
        self.tabs.select(self.menu_tab)
        self.status.set(action+': КБЖУ и покупки пересчитаны. При необходимости используйте «Отменить изменение».')
        changes=[{'day':d+1,'meal':MEALS[m],'before':previous[d][m].name,'after':r.name,'nutrition_after':recipe_nutrition(r)[0],'servings_after':servings_info(r).servings} for d,day in enumerate(new_week) for m,r in enumerate(day) if recipe_key(r)!=recipe_key(previous[d][m])]
        self.logger.info('manual_menu_change action=%s source=%s target=%s warnings=%s changes=%s',action,selected,target,len(self.menu_change_warnings(new_week)),changes)
        return True

    def undo_menu_change(self):
        if self.busy or not self.menu_history or not self.confirm_switch():return
        old,selected=self.menu_history[-1];current=self.week
        try:
            self.week=refresh_week(old,self.recipes)
            self.render_week()
        except (ValueError,OSError) as exc:
            self.week=current;self.logger.exception('menu_undo_failed')
            messagebox.showerror('Отмена не выполнена',str(exc),parent=self);return
        self.menu_history.pop()
        self.undo_button.config(state='normal' if self.menu_history else 'disabled')
        self.menu_day.set(f'День {selected[0]+1}');self.day_recipes.selection_set(str(selected[1]));self.show_day_recipe()
        self.status.set('Изменение отменено. КБЖУ и покупки пересчитаны.')
        self.logger.info('manual_menu_change_undone')

    def update_database_choices(self):
        self.database_labels={f'{n}. {d.name}':d.uid for n,d in enumerate(self.manager.databases,1)}
        self.database_combo.config(values=list(self.database_labels))
        if self.browse_database not in self.database_labels.values():self.browse_database=self.manager.databases[0].uid
        self.database_choice.set(next(label for label,uid in self.database_labels.items() if uid==self.browse_database))
        d=self.manager.get(self.browse_database)
        self.database_enabled.set(d.enabled)
        self.database_quota.set('' if d.quota is None else str(d.quota))
        self.update_database_summary()

    def update_database_summary(self):
        if not self.manager:return
        active=[d.name for d in self.manager.databases if d.enabled]
        count=sum(len(d.required) for d in self.manager.databases if d.enabled)
        self.database_summary.config(text='Включены: '+(', '.join(active) or 'ни одной')+f' · Обязательных: {count}')

    def save_database_options(self):
        if not self.manager:return True
        try:
            quota=number(self.database_quota.get(),'Блюд из базы',integer=True)
            if quota is not None and quota>21:raise ValueError('Из одной базы можно выбрать от 0 до 21 блюд за неделю.')
            d=self.manager.get(self.browse_database)
            old=(d.enabled,d.quota)
            d.enabled,d.quota=self.database_enabled.get(),quota
            try:self.manager.persist()
            except OSError:
                d.enabled,d.quota=old
                raise
            self.update_database_summary()
            return True
        except (ValueError,OSError) as exc:
            self.status.set(str(exc))
            return False

    def change_database(self,_=None):
        selected=self.database_labels.get(self.database_choice.get())
        if not selected or selected==self.browse_database:return
        if not self.confirm_switch() or not self.save_database_options():
            self.update_database_choices();return
        self.browse_database=selected;self.current=None;self.library_page=0
        self.search.set('');self.update_database_choices();self.load_editor(None);self.refresh_library()

    def select_database(self,uid):
        self.browse_database=uid;self.library_page=0;self.update_database_choices()

    def connect_database(self):
        if not self.confirm_switch():return
        path=filedialog.askopenfilename(parent=self,title='Подключить базу NJ-Cooking (JSON-массив рецептов)',filetypes=[('База рецептов NJ-Cooking','*.json')])
        if not path:return
        try:
            d=self.manager.connect(path)
            self.recipes=self.manager.all_recipes();self.current=None
            self.select_database(d.uid);self.load_editor(None);self.refresh_library()
            self.status.set(f'Подключена база «{d.name}». Файл: {d.path}')
        except (ValueError,OSError,KeyError,TypeError) as exc:messagebox.showerror('База не подключена',str(exc),parent=self)

    def create_database(self):
        if not self.confirm_switch():return
        path=filedialog.asksaveasfilename(parent=self,title='Создать отдельную базу',defaultextension='.json',filetypes=[('База рецептов','*.json')])
        if not path:return
        try:
            d=self.manager.create(path)
            self.recipes=self.manager.all_recipes();self.current=None
            self.select_database(d.uid);self.load_editor(None);self.refresh_library()
        except (ValueError,OSError) as exc:messagebox.showerror('База не создана',str(exc),parent=self)

    def click_required(self,event):
        row=self.library.identify_row(event.y)
        if row and self.library.identify_column(event.x)=='#1':
            self.toggle_required(int(row));return 'break'

    def space_required(self,_=None):
        rows=self.library.selection()
        if rows:self.toggle_required(int(rows[0]))
        return 'break'

    def toggle_required(self,index):
        try:
            recipe=self.recipes[index]
            enabled=self.manager.toggle_required(recipe)
            self.refresh_library();self.update_database_summary()
            self.status.set(('Обязательно включить: ' if enabled else 'Отметка снята: ')+recipe.name)
        except OSError as exc:self.status.set('Не удалось сохранить отметку: '+str(exc))

    def reset_required(self):
        d=self.manager.get(self.browse_database)
        if not d.required:
            self.status.set('В этой базе нет отмеченных рецептов.');return
        if messagebox.askyesno('Сброс избранных рецептов',f'Снять все {len(d.required)} отметок «обязательно в меню» в базе «{d.name}»?\nРецепты не удалятся, но перестанут быть обязательными. Отметки других баз сохранятся.',parent=self):
            old=set(d.required);d.required.clear()
            try:self.manager.persist()
            except OSError as exc:d.required=old;self.status.set(str(exc));return
            self.refresh_library();self.update_database_summary()

    def toggle_editor(self):
        if self.editor_expanded:
            self.library_split.insert(0,self.library_left,weight=1)
            self.expand_button.config(text='Развернуть карточку')
        else:
            self.library_split.forget(self.library_left)
            self.expand_button.config(text='Показать список рецептов')
        self.editor_expanded=not self.editor_expanded

    def reset_search(self):
        self.search.set('');self.only_required.set(False);self.reset_library_page()

    def reset_library_page(self):
        self.library_page=0;self.refresh_library()

    def page_library(self,delta):
        self.library_page=max(0,self.library_page+delta);self.refresh_library()

    def schedule_search(self):
        self.library_page=0
        if self.search_timer is not None:self.after_cancel(self.search_timer)
        self.search_timer=self.after(200,self.refresh_library)

    def refresh_library(self):
        if self.search_timer is not None:self.after_cancel(self.search_timer)
        self.search_timer=None
        if not self.manager:return
        self.selection_lock=True
        self.library.delete(*self.library.get_children())
        term=normalize(self.search.get());d=self.manager.get(self.browse_database)
        matches=[n for n,r in enumerate(self.recipes) if r.database_id==d.uid and term in normalize(r.name) and (not self.only_required.get() or r.uid in d.required)]
        self.library_page=min(self.library_page,max(0,(len(matches)-1)//300))
        visible=matches[self.library_page*300:(self.library_page+1)*300]
        if self.current is not None and self.current in matches and self.current not in visible:visible.append(self.current)
        for n in visible:
            r=self.recipes[n]
            state='Нет выхода' if readiness(r,False) else 'Неполное КБЖУ' if readiness(r) else 'КБЖУ есть'
            self.library.insert('','end',iid=str(n),text=r.name,values=('☑' if r.uid in d.required else '☐',state))
        if self.current is not None and self.library.exists(str(self.current)):self.library.selection_set(str(self.current))
        self.library_count.config(text=f'В базе: {len(d.recipes)} · Найдено: {len(matches)} · Страница {self.library_page+1}.\nОтметка «В меню» — обязательное включение хотя бы раз за неделю. Отмечено: {len(d.required)}.')
        self.selection_lock=False

    def auto_tags(self):
        from tagging import infer_tags
        tags=infer_tags(self.fields['name'].get(),ingredients=self.ingredients_data)
        for tag,var in self.recipe_tag_vars.items():var.set(tag in tags)
        self.update_preview()

    def snapshot(self):
        return ([v.get() for v in self.fields.values()], self.method.get('1.0', 'end-1c'), [i.__dict__.copy() for i in self.ingredients_data], [tag for tag,var in self.recipe_tag_vars.items() if var.get()])

    def dirty(self):
        return self.baseline is not None and self.snapshot() != self.baseline

    def confirm_switch(self):
        if not self.dirty():
            return True
        answer = messagebox.askyesnocancel('Несохранённый рецепт', 'Сохранить изменения перед переходом?\n«Нет» — продолжить без сохранения.', parent=self)
        if answer is None:
            return False
        return self.save_recipe() if answer else True

    def load_editor(self, index):
        self.current = index
        recipe = self.recipes[index] if index is not None else Recipe('', None, None, [])
        self.editor_uid=recipe.uid
        self.editor_database_id=recipe.database_id or ('personal' if self.manager.get(self.browse_database).bundled else self.browse_database)
        self.source_category=recipe.source_category
        self.loaded_source_metadata={key:copy.deepcopy(getattr(recipe,key)) for key in ('image_url','video_url','source_nutrition_per100g')}
        for tag,var in self.recipe_tag_vars.items():var.set(tag in recipe_tags(recipe))
        for key, var in self.fields.items():
            value = getattr(recipe, key)
            var.set('' if value is None else f'{value:g}' if isinstance(value, (int, float)) else value)
        self.ingredients_data = copy.deepcopy(recipe.ingredients)
        self.loaded_notes = list(recipe.import_notes)
        self.method.delete('1.0', 'end')
        self.method.insert('1.0', recipe.method)
        self.notes.config(text='\n'.join(recipe.import_notes)+(('\nДанные сайта на 100 г: '+nutrition_text(recipe.source_nutrition_per100g)) if recipe.source_nutrition_per100g else ''))
        self.editor_title.config(text='Новый рецепт' if index is None else recipe.name)
        self.editor_message.config(text='')
        self.refresh_ingredients()
        self.update_preview()
        self.baseline = copy.deepcopy(self.snapshot())

    def read_editor(self):
        recipe = Recipe(self.fields['name'].get().strip(), number(self.fields['servings'].get(), 'Исходное число порций', allow_zero=False),
                        number(self.fields['kcal'].get(), 'Калории'), copy.deepcopy(self.ingredients_data),
                        self.method.get('1.0', 'end-1c').strip(),
                        **{key: number(self.fields[key].get(), label) for key, label in zip(KEYS[1:], NUTRIENT_LABELS[1:])},
                        source_url=self.fields['source_url'].get().strip(), meal=self.fields['meal'].get() or 'Любой', import_notes=self.loaded_notes,
                        uid=self.editor_uid or Recipe('',None,None,[]).uid,source_category=getattr(self,'source_category',''),
                        tags=[tag for tag,var in self.recipe_tag_vars.items() if var.get()],database_id=self.editor_database_id,**self.loaded_source_metadata)
        if recipe.source_url:
            public_url(recipe.source_url)
        return recipe

    def update_preview(self):
        if not hasattr(self, 'nutrition_preview') or not hasattr(self, 'method'):
            return
        try:
            recipe = self.read_editor()
            values, estimated = recipe_nutrition(recipe)
            reasons = readiness(recipe)
            info=servings_info(recipe)
            unknown = [i.name for i in recipe.ingredients if ingredient_nutrition(i) is None]
            incomplete=[i.name for i in recipe.ingredients if ingredient_amount(i) is None or not i.unit]
            extra = ('\nНе рассчитаны продукты: ' + ', '.join(unknown[:5]) + '. Откройте продукт или введите КБЖУ блюда вручную.' if unknown and any(v is None for v in values.values()) else '')
            if incomplete:extra+='\nСписок покупок неполный — уточните количество/единицы: '+', '.join(incomplete[:5])+'. Это не блокирует ручное КБЖУ.'
            self.nutrition_preview.config(text=info.explanation + '\n' + ('≈ Оценка: ' if estimated else 'На порцию: ') + nutrition_text(values) +
                                          ('\nДля строгого контроля КБЖУ: ' + '; '.join(reasons) + '.' if reasons else '\n✓ Рецепт подходит для строгого контроля КБЖУ.') + extra)
        except ValueError as exc:
            self.nutrition_preview.config(text=str(exc))

    def new_recipe(self):
        if self.confirm_switch():
            if self.manager.get(self.browse_database).bundled:self.select_database('personal')
            self.load_editor(None)
            self.refresh_library()
            self.library.selection_remove(*self.library.selection())

    def select_recipe(self, _=None):
        if self.selection_lock:
            return
        selection = self.library.selection()
        if not selection:
            return
        index = int(selection[0])
        if index == self.current:
            return
        if self.confirm_switch():
            self.load_editor(index)
        else:
            self.refresh_library()

    def save_recipe(self):
        try:
            recipe = self.read_editor()
            validate_recipe(recipe)
            if any(n != self.current and r.database_id==recipe.database_id and normalize(r.name)==normalize(recipe.name) for n,r in enumerate(self.recipes)):
                raise ValueError('Такое название уже есть. Измените его или откройте существующий рецепт для редактирования.')
            updated = list(self.recipes)
            index = self.current
            if index is None:
                index = len(updated)
                updated.append(recipe)
            else:
                updated[index] = recipe
            self.manager.save_all(updated)
            self.recipes = updated
            if recipe.database_id!=self.browse_database:self.select_database(recipe.database_id)
            self.load_editor(index)
            self.refresh_library()
            reasons = readiness(recipe)
            text = ('Черновик сохранён. Для меню: '+ '; '.join(readiness(recipe,False))+'.' if readiness(recipe,False) else '✓ Сохранено. Можно использовать без обязательного контроля КБЖУ.' if reasons else '✓ Сохранено. Рецепт подходит для строгого контроля КБЖУ.')
            self.editor_message.config(text=text, foreground='#665000' if reasons else '#17623b')
            self.status.set(text)
            if self.week and any(recipe_key(r)==recipe_key(recipe) for day in self.week for r in day):
                self.week_message.set('Рецепт изменён. Нажмите «Пересчитать эти блюда» для обновления КБЖУ и покупок или повторите подбор из текущей выборки.')
                self.export_button.config(state='disabled')
            return True
        except (ValueError, OSError) as exc:
            self.logger.exception('recipe_save_failed name=%r',self.fields['name'].get())
            self.editor_message.config(text=str(exc), foreground='#a4262c')
            self.status.set('Рецепт не сохранён: ' + str(exc))
            return False

    def delete_recipe(self):
        if self.current is None:
            self.status.set('Сначала выберите рецепт в списке слева.')
            return
        if messagebox.askyesno('Удалить рецепт?', f'Удалить «{self.recipes[self.current].name}»? Предыдущая версия библиотеки останется в .bak.', parent=self):
            deleted_uid=recipe_key(self.recipes[self.current])
            updated = [r for n, r in enumerate(self.recipes) if n != self.current]
            try:
                self.manager.save_all(updated)
            except OSError as exc:
                messagebox.showerror('Не удалось сохранить', str(exc), parent=self)
                return
            self.recipes = updated
            if self.week and any(recipe_key(r)==deleted_uid for day in self.week for r in day):
                self.week_message.set('Рецепт из текущего меню удалён. Составьте новую неделю из библиотеки.')
                self.export_button.config(state='disabled')
            self.load_editor(None)
            self.refresh_library()

    def refresh_ingredients(self):
        self.ingredients_tree.delete(*self.ingredients_tree.get_children())
        for n, i in enumerate(self.ingredients_data):
            self.ingredients_tree.insert('', 'end', iid=str(n), text=i.name, values=('уточнить' if ingredient_amount(i) is None else ('≈ ' if i.amount is None else '') + f'{ingredient_amount(i):g}', i.unit or 'уточнить'))
        self.update_preview()

    def add_ingredient(self):
        dialog = IngredientDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.ingredients_data.append(dialog.result)
            self.refresh_ingredients()

    def edit_ingredient(self):
        selection = self.ingredients_tree.selection()
        if not selection:
            self.status.set('Выберите продукт в таблице; двойной щелчок тоже открывает редактирование.')
            return
        n = int(selection[0])
        dialog = IngredientDialog(self, self.ingredients_data[n])
        self.wait_window(dialog)
        if dialog.result:
            self.ingredients_data[n] = dialog.result
            self.refresh_ingredients()

    def remove_ingredient(self):
        selection = self.ingredients_tree.selection()
        if selection:
            del self.ingredients_data[int(selection[0])]
            self.refresh_ingredients()

    def paste_ingredients(self):
        dialog = tk.Toplevel(self)
        dialog.title('Вставить список продуктов')
        dialog.transient(self)
        ttk.Label(dialog, text='Одна строка — один продукт. Например: «Рис; 400; г», «200 г моркови».\nНераспознанные количества можно уточнить в таблице.', padding=12).pack(anchor='w')
        text = ScrolledText(dialog, width=65, height=15)
        text.pack(padx=12, pady=5)
        def apply():
            self.ingredients_data.extend(parse_ingredient(line) for line in text.get('1.0', 'end').splitlines() if line.strip())
            self.refresh_ingredients()
            dialog.destroy()
        ttk.Button(dialog, text='Добавить в рецепт', command=apply).pack(pady=10)
        dialog.grab_set()

    def open_source(self):
        url = self.fields['source_url'].get().strip()
        if not url:
            self.status.set('У этого рецепта пока нет ссылки. Вставьте адрес страницы в поле источника.')
            return
        try:
            webbrowser.open(public_url(url))
        except (ValueError, OSError) as exc:
            self.status.set(str(exc))

    def receive_imports(self, recipes):
        # The editor may have been changed during the background download.
        if not self.confirm_switch():
            self.status.set('Импорт отменён: текущий рецепт остался открыт.')
            return
        target='personal' if self.manager.get(self.browse_database).bundled else self.browse_database
        updated = list(self.recipes)
        for recipe in recipes:
            recipe.database_id=target
            original = recipe.name
            counter = 2
            while any(r.database_id==target and normalize(r.name)==normalize(recipe.name) for r in updated):
                recipe.name = f'{original} ({counter})'
                counter += 1
            updated.append(recipe)
        self.manager.save_all(updated)
        first = len(self.recipes)
        self.recipes = updated
        self.select_database(target)
        self.load_editor(first)
        self.refresh_library()
        self.tabs.select(self.library_tab)
        self.status.set(f'Импортировано: {len(recipes)}. Подтверждение не требуется; данные можно поправить в карточке.')

    def url_dialog(self):
        if self.busy:
            self.status.set('Дождитесь завершения текущей операции.')
            return
        dialog = tk.Toplevel(self)
        dialog.title('Импорт рецепта по ссылке')
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=20)
        frame.pack()
        ttk.Label(frame, text='Вставьте ссылку на страницу рецепта', font=(FONT, 12, 'bold')).pack(anchor='w')
        url = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=url, width=75)
        entry.pack(fill='x', pady=12)
        ttk.Label(frame, text='Поддерживаются Recipe JSON-LD, microdata (в том числе Povar.ru) и HTML RussianFood.com.\nИсточник сохранится в карточке и меню; фото и видео открываются на сайте.\nПлатные страницы, соцсети и сайты с блокировкой импорта могут не поддерживаться.', wraplength=580).pack(anchor='w')
        error = ttk.Label(frame, foreground='#a4262c', wraplength=580)
        error.pack(anchor='w', pady=5)
        def start():
            try:
                link = public_url(url.get())
            except ValueError as exc:
                error.config(text=str(exc))
                return
            dialog.destroy()
            self.run_background(lambda: import_url(link), self.receive_imports, 'Загружаю рецепт… Можно продолжать работу с карточками.')
        ttk.Button(frame, text='Загрузить и открыть для проверки', command=start).pack(anchor='w', pady=12)
        entry.focus_set()
        dialog.bind('<Return>', lambda _: start())
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        dialog.grab_set()

    def import_saved_html(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self,title='Сохранённая страница рецепта',filetypes=[('HTML-страница','*.html *.htm')])
        if not path:return
        try:
            from site_importers import saved_source
            from importing import decode_html,MAX_PAGE
            local=Path(path)
            if local.stat().st_size>MAX_PAGE:raise ValueError('HTML-файл слишком большой (более 4 МБ).')
            source=saved_source(decode_html(local.read_bytes()))
            if not source:
                source=simpledialog.askstring('Источник рецепта','Вставьте исходную ссылку на страницу рецепта:',parent=self)
                if not source:return
            self.receive_imports(import_html(path,source))
        except (ValueError,OSError) as exc:
            self.logger.exception('saved_html_import_failed')
            messagebox.showerror('Импорт HTML не выполнен',str(exc),parent=self)

    def import_word(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('Документ Word', '*.docx')])
        if not path:
            return
        try:
            self.receive_imports(import_docx(path))
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror('Не удалось прочитать Word', str(exc), parent=self)
        except Exception as exc:
            messagebox.showerror('Формат документа не поддерживается', f'Выберите исправный .docx. {exc}', parent=self)

    def add_examples(self):
        target='personal' if self.manager.get(self.browse_database).bundled else self.browse_database
        recipes = [r for r in example_recipes() if not any(old.database_id==target and normalize(r.name)==normalize(old.name) for old in self.recipes)]
        if not recipes:
            self.status.set('Все примеры уже добавлены. Перейдите к шагу 2.')
            return
        try:
            self.receive_imports(recipes)
            self.status.set('Добавлены учебные примеры с оценкой КБЖУ. Перейдите к шагу 2, чтобы попробовать подбор меню.')
        except OSError as exc:
            messagebox.showerror('Не удалось сохранить примеры', str(exc), parent=self)

    def reset_targets(self):
        for key, value in {**DEFAULT_TARGETS, 'tolerance': 200, 'macro_tolerance': 20, 'daily_kcal_spread':30,'daily_macro_spread':50,'protein_floor':75}.items():
            self.settings[key].set(f'{value:g}')

    def load_settings(self):
        if not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('неверный формат')
            self.require_nutrition.set(bool(data.get('_require_nutrition',False)))
            self.nutrition_mode.set('Строгий дневной' if data.get('_nutrition_mode')=='daily' else 'Недельный баланс')
            for tag,var in self.desired_tag_vars.items():var.set(tag in data.get('_desired_tags',[]))
            for key, value in data.items():
                if key in self.settings and isinstance(value, (str, int, float)):
                    self.settings[key].set(str(value))
        except (ValueError, OSError) as exc:
            self.status.set(f'Настройки не загружены; используются стартовые значения. {exc}')

    def read_settings(self):
        result = {key: number(self.settings[key].get(), label, default=DEFAULT_TARGETS[key], allow_zero=False)
                  for key, label in zip(KEYS, NUTRIENT_LABELS)}
        result.update(people=number(self.settings['people'].get(), 'Количество человек', default=2, integer=True, allow_zero=False),
                      portions=number(self.settings['portions'].get(), 'Порции на человека', default=1, allow_zero=False),
                      tolerance=number(self.settings['tolerance'].get(), 'Допуск калорий', default=200),
                      macro_tolerance=number(self.settings['macro_tolerance'].get(), 'Допуск БЖУ', default=20))
        if result['macro_tolerance'] > 100:
            raise ValueError('Допуск БЖУ: укажите от 0 до 100%.')
        result['macro_tolerance'] /= 100
        result['nutrition_mode']='weekly' if self.nutrition_mode.get()=='Недельный баланс' else 'daily'
        for key,label,default in (('daily_kcal_spread','Дневной разброс калорий',30),('daily_macro_spread','Дневной разброс БЖУ',50),('protein_floor','Минимум белка',75)):
            value=number(self.settings[key].get(),label,default=default)
            if value>100:raise ValueError(label+': укажите от 0 до 100%.')
            result[key]=value/100
        return result

    def settings_payload(self):
        return {**{k:v.get() for k,v in self.settings.items()},'_require_nutrition':self.require_nutrition.get(),
                '_nutrition_mode':'weekly' if self.nutrition_mode.get()=='Недельный баланс' else 'daily',
                '_desired_tags':[t for t,v in self.desired_tag_vars.items() if v.get()]}

    def generate(self):
        if self.busy or not self.confirm_switch() or not self.save_database_options():return
        try:
            context=self.read_settings()
            context.update(require_nutrition=self.require_nutrition.get(),
                           desired_tags=[t for t,v in self.desired_tag_vars.items() if v.get()],
                           excluded=self.settings['excluded'].get().split(','),wanted=self.settings['wanted'].get().split(','))
            context.update(required_ids=self.manager.required_keys(),database_limits=self.manager.limits(),enabled_databases=[d.uid for d in self.manager.databases if d.enabled])
            if not context['enabled_databases']:raise ValueError('Включите хотя бы одну базу на шаге 1.')
            save_json(self.settings_path,self.settings_payload())
        except (ValueError,OSError) as exc:
            self.logger.exception('plan_request_validation_failed')
            self.plan_message.config(text=str(exc),foreground='#a4262c')
            return
        self.start_plan(context,self.manager.active_recipes())

    def start_plan(self, context, recipes):
        context=copy.deepcopy(context)
        context.pop('accepted_nutrition_deviations',None)
        recipes=copy.deepcopy(recipes)
        request_id=uuid.uuid4().hex[:10]
        seed=int(request_id,16)
        log_plan(self.logger,request_id,{**context,'seed':seed},recipes)
        self.logger.info('request=%s database_sources=%s',request_id,[{'id':d.uid,'name':d.name,'enabled':d.enabled,'quota':d.quota,'recipes':len(d.recipes),'required':len(d.required)} for d in self.manager.databases])
        self.plan_message.config(text='Подбираю неделю…',foreground='#334155')
        def work():
            arguments=dict(people=context['people'],portions=context['portions'],target=context['kcal'],tolerance=context['tolerance'],
                           excluded=context['excluded'],wanted=context['wanted'],seed=seed,
                           macro_targets={k:context[k] for k in KEYS[1:]},macro_tolerance=context['macro_tolerance'],
                           require_nutrition=context['require_nutrition'],desired_tags=context['desired_tags'],
                           required_ids=context.get('required_ids',[]),database_limits=context.get('database_limits',{}),**balance_options(context))
            try:return plan(recipes,**arguments)
            except NutritionSearchFailure as failure:
                if not context['require_nutrition']:raise
                self.logger.info('request=%s searching_preview_with_nutrition_deviations reason=%s',request_id,str(failure))
                week=plan(recipes,**arguments,allow_nutrition_deviations=True)
                return {'preview_week':week,'reason':str(failure)}
        def done(week):
            accepted=False
            if isinstance(week,dict) and 'preview_week' in week:
                proposal=week
                if not self.confirm_nutrition_preview(proposal['preview_week'],context,proposal['reason']):
                    self.logger.info('request=%s nutrition_preview_rejected',request_id)
                    self.plan_message.config(text='Вариант с отклонениями не принят. Текущее меню сохранено.',foreground='#9a6700')
                    return
                week=proposal['preview_week'];accepted=True
                context['accepted_nutrition_deviations']=True
                self.logger.info('request=%s nutrition_preview_accepted issues=%s',request_id,week_issues(week,context['portions'],{k:context[k] for k in KEYS},context['tolerance'],context['macro_tolerance'],**balance_options(context)))
            self.menu_history=[];self.undo_button.config(state='disabled')
            context.setdefault('required_names',{recipe_key(r):r.name for r in recipes if recipe_key(r) in context.get('required_ids',[])})
            self.last_plan_settings=context
            self.week=week
            self.render_week()
            self.tabs.select(self.menu_tab)
            self.plan_message.config(text='✓ Меню принято с отклонениями КБЖУ.' if accepted else '✓ Меню составлено.'+(' Пределы КБЖУ соблюдены.' if context['require_nutrition'] else ' Обязательная проверка КБЖУ выключена.'),foreground='#9a6700' if accepted else '#17623b')
            self.status.set('Меню готово. Для правок откройте блюдо в списке, сохраните изменения и пересчитайте выборку.')
        self.run_background(work,done,'Составляю меню на неделю…',request_id=request_id)

    def confirm_nutrition_preview(self,week,context,reason):
        dialog=tk.Toplevel(self)
        dialog.title('Вариант меню с отклонениями КБЖУ')
        dialog.geometry('1000x720');dialog.minsize(780,520)
        dialog.transient(self);dialog.grab_set()
        accepted=[False]
        footer=ttk.Frame(dialog,padding=12);footer.pack(side='bottom',fill='x')
        def accept():accepted[0]=True;dialog.destroy()
        ttk.Button(footer,text='Принять меню с этими отклонениями',command=accept).pack(side='left')
        ttk.Button(footer,text='Отмена — сохранить текущее меню',command=dialog.destroy).pack(side='right')
        ttk.Label(dialog,text='Найден вариант с отклонениями от выбранного режима КБЖУ. Проверьте дневные границы и среднее за неделю.\nИсключения, выход, полнота КБЖУ, обязательные блюда и квоты баз остаются условиями подбора.',wraplength=940,padding=12).pack(fill='x')
        text=ScrolledText(dialog,wrap='word',font=(FONT,11));text.pack(fill='both',expand=True,padx=12,pady=8)
        issues=week_issues(week,context['portions'],{k:context[k] for k in KEYS},context['tolerance'],context['macro_tolerance'],**balance_options(context))
        names={d.uid:d.name for d in self.manager.databases}
        quotas='\n'.join(f'{names.get(db,db)}: задано {quota}, получено {sum(r.database_id==db for day in week for r in day)}' for db,quota in context.get('database_limits',{}).items()) or 'Квоты количества блюд по базам не заданы.'
        summary='\n'.join(f'День {n}: '+', '.join(r.name for r in day) for n,day in enumerate(week,1))
        mode='Недельный баланс: проверены среднее за неделю и дневные границы.' if context.get('nutrition_mode')=='weekly' else 'Строгий дневной режим.'
        text.insert('1.0',mode+'\n\nОТКЛОНЕНИЯ ОТ ГРАНИЦ (не от центра цели)\n'+'\n'.join(issues)+'\n\nКВОТЫ БАЗ\n'+quotas+'\n\nБЛЮДА\n'+summary+'\n\nПРИЧИНА ОСТАНОВКИ СТРОГОГО ПОДБОРА\n'+reason+'\n\nЭто найденный вариант, а не доказанно ближайшее возможное меню.')
        text.config(state='disabled')
        self.wait_window(dialog)
        return accepted[0]

    def render_week(self):
        c=self.last_plan_settings
        save_json(self.menu_path,{'uids':[[recipe_key(r) for r in day] for day in self.week],'context':c})
        context={**c,'database_names':{d.uid:d.name for d in self.manager.databases},'required_names':{**c.get('required_names',{}),**{recipe_key(r):r.name for r in self.recipes}}}
        extra=arrangement_warnings(self.week,context,{d.uid for d in self.manager.databases if d.enabled})
        self.report=week_report(self.week,c['people'],c['portions'],{k:c[k] for k in KEYS},c['tolerance'],c['macro_tolerance'],c['require_nutrition'],extra_warnings=extra,**balance_options(c))
        from collections import Counter
        dbcounts=Counter(r.database_id for day in self.week for r in day)
        sources='; '.join(f'{self.manager.get(uid).name}: {count}' for uid,count in dbcounts.items())
        required=set(c.get('required_ids',[]));present={recipe_key(r) for day in self.week for r in day}
        self.report='Блюд из баз: '+sources+'\n'+f'Обязательных рецептов включено: {len(required&present)} из {len(required)}.\n\n'+self.report
        self.set_output(self.report)
        self.week_tree.delete(*self.week_tree.get_children())
        for d,day in enumerate(self.week):
            for m,r in enumerate(day):self.week_tree.insert('','end',iid=f'{d}-{m}',text=f'{d+1}. {r.name}',values=(MEALS[m],))
        for button in (self.export_button,self.recalculate_button,self.replan_button):button.config(state='normal')
        from reports import week_issues
        issues=week_issues(self.week,c['portions'],{k:c[k] for k in KEYS},c['tolerance'],c['macro_tolerance'],**balance_options(c))+extra
        self.week_message.set('Пересчитано. Блюда сохранены. '+('Есть предупреждения по КБЖУ или условиям меню — подробности в отчёте.' if issues else 'Цели КБЖУ выбранного режима соблюдены.'))
        self.render_day_menu()

    def edit_week_recipe(self):
        selection=self.week_tree.selection()
        if not selection or not self.week:
            self.status.set('Выберите блюдо в списке недельного меню.')
            return
        if not self.confirm_switch():return
        d,m=map(int,selection[0].split('-'))
        self.open_recipe_editor(self.week[d][m])

    def open_recipe_editor(self,recipe):
        key=recipe_key(recipe)
        index=next((n for n,r in enumerate(self.recipes) if recipe_key(r)==key),None)
        if index is None:
            self.status.set('Этот рецепт удалён. Составьте меню заново.')
            return
        self.select_database(self.recipes[index].database_id)
        self.search.set('')
        self.only_required.set(False)
        self.load_editor(index)
        self.refresh_library()
        self.tabs.select(self.library_tab)
        if not self.editor_expanded:self.toggle_editor()

    def recalculate_week(self):
        if self.busy or not self.week or not self.confirm_switch():return
        try:
            origin=self.tabs.select()
            self.week=refresh_week(self.week,self.recipes)
            self.render_week()
            self.tabs.select(self.menu_tab if origin==str(self.menu_tab) else self.result_tab)
        except (ValueError,OSError) as exc:self.status.set(str(exc))

    def replan_current(self):
        if self.busy or not self.week or not self.confirm_switch():return
        try:
            week=refresh_week(self.week,self.recipes)
            if not self.save_database_options():return
            enabled={d.uid for d in self.manager.databases if d.enabled}
            recipes=list({recipe_key(r):r for day in week for r in day if r.database_id in enabled}.values())
            context={**self.last_plan_settings,'required_ids':self.manager.required_keys(),'database_limits':self.manager.limits(),'enabled_databases':sorted(enabled)}
            self.start_plan(context,recipes)
        except ValueError as exc:self.status.set(str(exc))

    def load_saved_week(self):
        if not self.menu_path.exists():return
        try:
            data=json.loads(self.menu_path.read_text(encoding='utf-8'))
            lookup={recipe_key(r):r for r in self.recipes}
            from collections import Counter
            counts=Counter(r.uid for r in self.recipes)
            lookup.update({r.uid:r for r in self.recipes if counts[r.uid]==1})
            if len(data['uids'])!=7 or any(len(day)!=3 for day in data['uids']):raise ValueError('неверная структура недели')
            self.week=[tuple(lookup[uid] for uid in day) for day in data['uids']]
            self.last_plan_settings=data['context']
            self.render_week()
        except (ValueError,KeyError,TypeError,OSError) as exc:
            self.logger.exception('menu_restore_failed')
            self.week=None
            self.status.set('Предыдущее меню не восстановлено: '+str(exc))

    def show_log_location(self):
        if self.log_path:
            messagebox.showinfo('Журнал диагностики',f'Версия {APP_VERSION}\n\nФайл журнала:\n{self.log_path}\n\nПосле ошибки закройте программу и пришлите этот файл. В нём есть настройки подбора и названия выбранных блюд; полные тексты рецептов и переменные окружения не копируются.',parent=self)
        else:messagebox.showwarning('Журнал недоступен','Не удалось создать журнал. Проверьте права на папку данных.',parent=self)

    def report_callback_exception(self,exc_type,exc_value,traceback):
        self.logger.error('tk_callback_failed',exc_info=(exc_type,exc_value,traceback))
        messagebox.showerror('Ошибка интерфейса',str(exc_value)+'\n\nЖурнал: '+str(self.log_path or 'недоступен'),parent=self)

    def run_background(self, work, success, text,request_id=None):
        request_id=request_id or uuid.uuid4().hex[:10]
        self.logger.info('request=%s operation_started=%s',request_id,text)
        self.busy = True
        self.generate_button.config(state='disabled')
        self.status.set(text)
        def worker():
            try:
                result=work()
                self.logger.info('request=%s operation_success',request_id)
                self.events.put((success,result,None))
            except Exception as exc:
                self.logger.exception('request=%s operation_failed',request_id)
                self.events.put((success, None, exc))
        threading.Thread(target=worker,daemon=True,name='task-'+request_id).start()

    def poll_events(self):
        try:
            while True:
                success, result, error = self.events.get_nowait()
                self.busy = False
                self.generate_button.config(state='normal')
                if error:
                    message=str(error)
                    for db in self.manager.databases:message=message.replace(db.uid,db.name)
                    message+='\n\nЖурнал диагностики: '+str(self.log_path or 'не удалось создать')
                    self.status.set(message)
                    self.plan_message.config(text=message, foreground='#a4262c')
                    messagebox.showerror('Не удалось завершить операцию',message,parent=self)
                else:
                    try:
                        success(result)
                    except (OSError, ValueError) as exc:
                        self.logger.exception('background_result_save_failed')
                        self.status.set(str(exc))
                        messagebox.showerror('Не удалось сохранить результат', str(exc), parent=self)
        except queue.Empty:
            pass
        self.poll_id = self.after(80, self.poll_events)

    def set_output(self,text):
        self.set_reader_text(self.output,text)

    def set_reader_text(self,widget,text):
        import re
        widget.config(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', text)
        for n, match in enumerate(re.finditer(r'https?://[^\s]+', text)):
            tag = f'url_{n}'
            widget.tag_add(tag, f'1.0+{match.start()}c', f'1.0+{match.end()}c')
            widget.tag_config(tag, foreground='#1769aa', underline=True)
            widget.tag_bind(tag, '<Button-1>', lambda _, url=match.group(): webbrowser.open(public_url(url)))
        widget.config(state='disabled')

    def export(self):
        if not self.report:
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension='.txt', initialfile='Меню и покупки.txt', filetypes=[('Текст UTF-8', '*.txt')])
        if path:
            try:
                Path(path).write_text(self.report, encoding='utf-8-sig')
                self.status.set(f'Меню сохранено: {path}')
            except OSError as exc:
                messagebox.showerror('Не удалось сохранить', str(exc), parent=self)

    def destroy(self):
        if self.search_timer is not None:self.after_cancel(self.search_timer)
        if hasattr(self, 'poll_id'):
            self.after_cancel(self.poll_id)
        if hasattr(self,'logger'):
            self.logger.info('application_closed')
            close_logging(self.logger)
        super().destroy()

    def close(self):
        if self.confirm_switch():
            self.destroy()


if __name__ == '__main__':
    import sys
    if '--self-test' in sys.argv:
        from storage import bundled_recipes
        from catalog import records
        assert len(bundled_recipes())==13703 and len(records())>8000
    else:
        logger,path=configure_logging(DATA.parent/'logs')
        try:App().mainloop()
        except Exception:
            logger.exception('fatal_startup_or_mainloop_error')
            raise
