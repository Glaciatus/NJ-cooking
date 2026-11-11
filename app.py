"""Family meal planner: guided local desktop UI, standard Python/Tk only."""
import copy
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
import webbrowser
from core import Recipe, Ingredient, MEALS, validate_recipe, readiness, plan
from nutrition import KEYS, DEFAULT_TARGETS, FOODS, normalize, number, ingredient_nutrition, recipe_nutrition, nutrition_text
from importing import import_url, public_url, parse_ingredient, import_docx
from storage import load_recipes, save_recipes, save_json
from reports import week_report
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
        self.name.trace_add('write', lambda *_: self.reference_hint())
        self.reference_hint()
        box = ttk.LabelFrame(frame, text='Необязательно: своё КБЖУ на 100 г', padding=8)
        box.grid(row=8, column=0, sticky='ew', pady=5)
        self.values = [tk.StringVar(value='' if i.per100g is None else f'{i.per100g[n]:g}') for n in range(4)]
        for n, (label, var) in enumerate(zip(NUTRIENT_LABELS, self.values)):
            entry_row(box, label, var, n*2)
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
        food = FOODS.get(normalize(self.name.get()))
        text = ('Есть в справочнике: ' + nutrition_text(dict(zip(KEYS, food.values))) + ' на 100 г. Значения приблизительные.' if food else
                'Нет точного совпадения в справочнике. Можно задать КБЖУ продукта ниже или КБЖУ всего блюда в карточке рецепта.')
        if food and food.piece_g:
            text += f' Принято: 1 шт ≈ {food.piece_g:g} г; массу можно изменить ниже.'
        if food and food.density:
            text += f' Принято: 1 мл ≈ {food.density:g} г.'
        self.hint.config(text=text)

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
                                     number(self.mass.get(), 'Масса единицы', allow_zero=False))
            self.destroy()
        except ValueError as exc:
            self.error.config(text=str(exc))


class App(tk.Tk):
    def __init__(self, data_path=DATA):
        super().__init__()
        self.title('Семейное меню • рецепты, КБЖУ и покупки')
        self.geometry('1240x860')
        self.minsize(1000, 700)
        self.data_path = Path(data_path)
        self.settings_path = self.data_path.with_name('settings.json')
        self.recipes = []
        self.current = None
        self.ingredients_data = []
        self.loaded_notes = []
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
        ttk.Label(header, text='Семейное меню', style='Title.TLabel').pack(anchor='w')
        ttk.Label(header, text='1. Добавьте и проверьте рецепты → 2. Выберите цели → 3. Получите меню и список покупок', style='Subtitle.TLabel').pack(anchor='w', pady=(4, 0))
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=15)
        self.library_tab, self.settings_tab, self.result_tab = [ttk.Frame(self.tabs, padding=12) for _ in range(3)]
        for frame, title in zip((self.library_tab, self.settings_tab, self.result_tab), ('1. Мои рецепты', '2. Семья и цели КБЖУ', '3. Меню и покупки')):
            self.tabs.add(frame, text=title)
        self.status = tk.StringVar(value='Начните с кнопки «Новый рецепт», «Из ссылки» или «Примеры».')
        ttk.Label(self, textvariable=self.status, padding=(18, 10), wraplength=1100).pack(fill='x')
        self.build_library()
        self.build_settings()
        self.build_result()
        try:
            self.recipes = load_recipes(self.data_path)
        except ValueError as exc:
            messagebox.showerror('Рецепты не загружены — данные сохранены', str(exc), parent=self)
            self.after_idle(self.destroy)
            return
        self.load_settings()
        self.refresh_library()
        self.load_editor(None)
        self.poll_id = self.after(80, self.poll_events)
        self.protocol('WM_DELETE_WINDOW', self.close)

    def build_library(self):
        split = ttk.Panedwindow(self.library_tab, orient='horizontal')
        split.pack(fill='both', expand=True)
        left = ttk.Frame(split, width=330)
        right = ttk.Frame(split)
        split.add(left, weight=1)
        split.add(right, weight=3)
        toolbar = ttk.Frame(left)
        toolbar.pack(fill='x', pady=(0, 8))
        ttk.Button(toolbar, text='+ Новый', command=self.new_recipe).pack(side='left')
        ttk.Button(toolbar, text='Из ссылки', command=self.url_dialog).pack(side='left', padx=3)
        ttk.Button(toolbar, text='Word', command=self.import_word).pack(side='left')
        self.search = tk.StringVar()
        ttk.Label(left, text='Найти рецепт').pack(anchor='w')
        ttk.Entry(left, textvariable=self.search).pack(fill='x', pady=5)
        self.search.trace_add('write', lambda *_: self.refresh_library())
        self.library = ttk.Treeview(left, columns=('state',), show='tree headings', selectmode='browse', height=14)
        self.library.heading('#0', text='Название')
        self.library.heading('state', text='Статус')
        self.library.column('#0', width=190)
        self.library.column('state', width=110)
        scroll = ttk.Scrollbar(left, orient='vertical', command=self.library.yview)
        self.library.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.library.pack(fill='both', expand=True)
        self.library.bind('<<TreeviewSelect>>', self.select_recipe)
        self.library_count = ttk.Label(left, wraplength=310)
        self.library_count.pack(anchor='w', pady=8)
        actions = ttk.Frame(left)
        actions.pack(fill='x')
        ttk.Button(actions, text='Примеры', command=self.add_examples).pack(side='left')
        ttk.Button(actions, text='Удалить', command=self.delete_recipe).pack(side='left', padx=4)
        ttk.Button(left, text='Далее: семья и цели →', command=lambda: self.tabs.select(self.settings_tab)).pack(fill='x', pady=10)
        fixed_actions = ttk.Frame(right, padding=(15, 0, 8, 8))
        fixed_actions.pack(fill='x')
        ttk.Button(fixed_actions, text='Сохранить рецепт / подтвердить импорт', style='Primary.TButton', command=self.save_recipe).pack(side='left')
        ttk.Label(fixed_actions, text='Ctrl+S', foreground='#666666').pack(side='left', padx=8)
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
        ttk.Label(form, text='Можно сохранить неполный рецепт. Для меню потребуются порции, количества продуктов и полное КБЖУ.', wraplength=650).pack(anchor='w', pady=5)
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
        ttk.Label(nutrition, text='Пустое поле = расчёт по ингредиентам. Введённое число заменяет расчёт. Ноль означает 0, а не отсутствие данных.', wraplength=650).grid(row=2, column=0, columnspan=4, sticky='w', pady=5)
        self.nutrition_preview = ttk.Label(nutrition, wraplength=650)
        self.nutrition_preview.grid(row=3, column=0, columnspan=4, sticky='w')
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
        ttk.Button(form, text='Сохранить рецепт / подтвердить импорт', style='Primary.TButton', command=self.save_recipe).pack(anchor='w', pady=8)
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
            'tolerance': '200', 'macro_tolerance': '20', 'excluded': '', 'wanted': ''}.items()}
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
        restrictions = ttk.LabelFrame(content, text='Продукты', padding=12)
        restrictions.pack(fill='x', pady=8)
        restrictions.columnconfigure(0, weight=1)
        entry_row(restrictions, 'Исключить (через запятую)', self.settings['excluded'], 0, width=80)
        entry_row(restrictions, 'Использовать остатки: каждый продукт хотя бы раз за неделю (через запятую)', self.settings['wanted'], 2, width=80)
        ttk.Label(restrictions, text='Сопоставление по части названия: «молок» найдёт «молоко». Количество остатков пока не учитывается.', wraplength=1000).grid(row=4, column=0, sticky='w', padx=5, pady=5)

    def build_result(self):
        actions = ttk.Frame(self.result_tab)
        actions.pack(fill='x', pady=(0, 8))
        ttk.Button(actions, text='← Изменить цели', command=lambda: self.tabs.select(self.settings_tab)).pack(side='left')
        self.export_button = ttk.Button(actions, text='Сохранить меню и покупки (.txt)', command=self.export, state='disabled')
        self.export_button.pack(side='left', padx=8)
        self.output = ScrolledText(self.result_tab, wrap='word', state='disabled', font=(FONT, 10))
        self.output.pack(fill='both', expand=True)
        self.set_output('Здесь появятся меню, КБЖУ на блюдо, день и неделю, ссылки на рецепты и список покупок.\n\nСначала добавьте рецепты на шаге 1, затем нажмите «Составить меню» на шаге 2.')

    def refresh_library(self):
        self.selection_lock = True
        self.library.delete(*self.library.get_children())
        term = normalize(self.search.get())
        for n, recipe in enumerate(self.recipes):
            if term in normalize(recipe.name):
                self.library.insert('', 'end', iid=str(n), text=recipe.name, values=('Уточнить' if readiness(recipe) else 'Готов к меню',))
        if self.current is not None and self.library.exists(str(self.current)):
            self.library.selection_set(str(self.current))
        ready = sum(not readiness(r) for r in self.recipes)
        self.library_count.config(text=f'Всего: {len(self.recipes)} · Готовы к меню: {ready}\n«Уточнить» — откройте рецепт и прочитайте подсказку.')
        self.selection_lock = False

    def snapshot(self):
        return ([v.get() for v in self.fields.values()], self.method.get('1.0', 'end-1c'), [i.__dict__.copy() for i in self.ingredients_data])

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
        for key, var in self.fields.items():
            value = getattr(recipe, key)
            var.set('' if value is None else f'{value:g}' if isinstance(value, (int, float)) else value)
        self.ingredients_data = copy.deepcopy(recipe.ingredients)
        self.loaded_notes = list(recipe.import_notes)
        self.method.delete('1.0', 'end')
        self.method.insert('1.0', recipe.method)
        self.notes.config(text='\n'.join(recipe.import_notes))
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
                        source_url=self.fields['source_url'].get().strip(), meal=self.fields['meal'].get() or 'Любой', import_notes=self.loaded_notes)
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
            unknown = [i.name for i in recipe.ingredients if ingredient_nutrition(i) is None]
            extra = ('\nНе рассчитаны продукты: ' + ', '.join(unknown[:5]) + '. Откройте продукт или введите КБЖУ блюда вручную.' if unknown and any(v is None for v in values.values()) else '')
            self.nutrition_preview.config(text=('≈ Оценка: ' if estimated else 'На порцию: ') + nutrition_text(values) +
                                          ('\nДля меню: ' + '; '.join(reasons) + '.' if reasons else '\n✓ После сохранения рецепт готов к меню.') + extra)
        except ValueError as exc:
            self.nutrition_preview.config(text=str(exc))

    def new_recipe(self):
        if self.confirm_switch():
            self.load_editor(None)
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
            if any(n != self.current and normalize(r.name) == normalize(recipe.name) for n, r in enumerate(self.recipes)):
                raise ValueError('Такое название уже есть. Измените его или откройте существующий рецепт для редактирования.')
            updated = list(self.recipes)
            index = self.current
            if index is None:
                index = len(updated)
                updated.append(recipe)
            else:
                updated[index] = recipe
            save_recipes(self.data_path, updated)
            self.recipes = updated
            self.load_editor(index)
            self.refresh_library()
            reasons = readiness(recipe)
            text = ('Черновик сохранён. Для меню: ' + '; '.join(reasons) + '.' if reasons else '✓ Рецепт сохранён и готов к меню. Добавьте другие рецепты или переходите к шагу 2.')
            self.editor_message.config(text=text, foreground='#665000' if reasons else '#17623b')
            self.status.set(text)
            return True
        except (ValueError, OSError) as exc:
            self.editor_message.config(text=str(exc), foreground='#a4262c')
            self.status.set('Рецепт не сохранён: ' + str(exc))
            return False

    def delete_recipe(self):
        if self.current is None:
            self.status.set('Сначала выберите рецепт в списке слева.')
            return
        if messagebox.askyesno('Удалить рецепт?', f'Удалить «{self.recipes[self.current].name}»? Предыдущая версия библиотеки останется в .bak.', parent=self):
            updated = [r for n, r in enumerate(self.recipes) if n != self.current]
            try:
                save_recipes(self.data_path, updated)
            except OSError as exc:
                messagebox.showerror('Не удалось сохранить', str(exc), parent=self)
                return
            self.recipes = updated
            self.load_editor(None)
            self.refresh_library()

    def refresh_ingredients(self):
        self.ingredients_tree.delete(*self.ingredients_tree.get_children())
        for n, i in enumerate(self.ingredients_data):
            self.ingredients_tree.insert('', 'end', iid=str(n), text=i.name, values=('уточнить' if i.amount is None else f'{i.amount:g}', i.unit or 'уточнить'))
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
        updated = list(self.recipes)
        for recipe in recipes:
            original = recipe.name
            counter = 2
            while any(normalize(r.name) == normalize(recipe.name) for r in updated):
                recipe.name = f'{original} ({counter})'
                counter += 1
            updated.append(recipe)
        save_recipes(self.data_path, updated)
        first = len(self.recipes)
        self.recipes = updated
        self.load_editor(first)
        self.refresh_library()
        self.tabs.select(self.library_tab)
        self.status.set(f'Импортировано: {len(recipes)}. Откройте каждый рецепт, проверьте данные и нажмите «Сохранить рецепт / подтвердить импорт».')

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
        ttk.Label(frame, text='Поддерживаются сайты с разметкой Recipe (JSON-LD).\nИсточник сохранится в карточке и меню; фото и видео открываются на сайте.\nПлатные страницы, соцсети и сайты с блокировкой импорта могут не поддерживаться.', wraplength=580).pack(anchor='w')
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
        recipes = [r for r in example_recipes() if not any(normalize(r.name) == normalize(old.name) for old in self.recipes)]
        if not recipes:
            self.status.set('Все примеры уже добавлены. Перейдите к шагу 2.')
            return
        try:
            self.receive_imports(recipes)
            self.status.set('Добавлены учебные примеры с оценкой КБЖУ. Перейдите к шагу 2, чтобы попробовать подбор меню.')
        except OSError as exc:
            messagebox.showerror('Не удалось сохранить примеры', str(exc), parent=self)

    def reset_targets(self):
        for key, value in {**DEFAULT_TARGETS, 'tolerance': 200, 'macro_tolerance': 20}.items():
            self.settings[key].set(f'{value:g}')

    def load_settings(self):
        if not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('неверный формат')
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
        return result

    def generate(self):
        if self.busy:
            return
        if not self.confirm_switch():
            return
        try:
            settings = self.read_settings()
            save_json(self.settings_path, {k: v.get() for k, v in self.settings.items()})
        except (ValueError, OSError) as exc:
            self.plan_message.config(text=str(exc), foreground='#a4262c')
            return
        recipes = copy.deepcopy(self.recipes)
        excluded, wanted = (self.settings[k].get().split(',') for k in ('excluded', 'wanted'))
        targets = {k: settings[k] for k in KEYS}
        self.plan_message.config(text='Подбираю сочетания в пределах КБЖУ…', foreground='#334155')
        def work():
            week = plan(recipes, settings['people'], settings['portions'], settings['kcal'], settings['tolerance'], excluded, wanted,
                        macro_targets={k: settings[k] for k in KEYS[1:]}, macro_tolerance=settings['macro_tolerance'])
            return week, week_report(week, settings['people'], settings['portions'], targets, settings['tolerance'], settings['macro_tolerance'])
        def done(result):
            self.week, self.report = result
            self.set_output(self.report)
            self.export_button.config(state='normal')
            self.plan_message.config(text='✓ Меню составлено. Каждый день соответствует заданным пределам КБЖУ.', foreground='#17623b')
            self.tabs.select(self.result_tab)
            self.status.set('Меню готово. Ссылки можно открыть нажатием; список покупок находится в конце. Сохраните результат кнопкой над меню.')
        self.run_background(work, done, 'Составляю меню на неделю…')

    def run_background(self, work, success, text):
        self.busy = True
        self.generate_button.config(state='disabled')
        self.status.set(text)
        def worker():
            try:
                self.events.put((success, work(), None))
            except Exception as exc:
                self.events.put((success, None, exc))
        threading.Thread(target=worker, daemon=True).start()

    def poll_events(self):
        try:
            while True:
                success, result, error = self.events.get_nowait()
                self.busy = False
                self.generate_button.config(state='normal')
                if error:
                    self.status.set(str(error))
                    self.plan_message.config(text=str(error), foreground='#a4262c')
                    messagebox.showerror('Не удалось завершить операцию', str(error), parent=self)
                else:
                    try:
                        success(result)
                    except (OSError, ValueError) as exc:
                        self.status.set(str(exc))
                        messagebox.showerror('Не удалось сохранить результат', str(exc), parent=self)
        except queue.Empty:
            pass
        self.poll_id = self.after(80, self.poll_events)

    def set_output(self, text):
        import re
        self.output.config(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', text)
        for n, match in enumerate(re.finditer(r'https?://[^\s]+', text)):
            tag = f'url_{n}'
            self.output.tag_add(tag, f'1.0+{match.start()}c', f'1.0+{match.end()}c')
            self.output.tag_config(tag, foreground='#1769aa', underline=True)
            self.output.tag_bind(tag, '<Button-1>', lambda _, url=match.group(): webbrowser.open(public_url(url)))
        self.output.config(state='disabled')

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
        if hasattr(self, 'poll_id'):
            self.after_cancel(self.poll_id)
        super().destroy()

    def close(self):
        if self.confirm_switch():
            self.destroy()


if __name__ == '__main__':
    App().mainloop()
