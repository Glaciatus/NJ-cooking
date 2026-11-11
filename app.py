import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from core import Recipe, ingredients_from_text, word_text, totals, plan

DATA = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'NJ-cooking' / 'recipes.json'

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Семейное меню')
        self.geometry('1100x800')
        self.recipes = []
        if DATA.exists():
            try:
                self.recipes = [Recipe.from_dict(r) for r in json.loads(DATA.read_text(encoding='utf-8'))]
            except Exception as e:
                messagebox.showerror('Не удалось прочитать рецепты', str(e))
                self.destroy()
                return
        tabs = ttk.Notebook(self)
        tabs.pack(fill='both', expand=True)
        editor, planner = ttk.Frame(tabs), ttk.Frame(tabs)
        tabs.add(editor, text='Рецепты и Word')
        tabs.add(planner, text='Меню на неделю')
        self.fields = {}
        for label, default in [('Название', ''), ('Порций в исходном рецепте', '4'), ('Ккал на одну порцию', '')]:
            ttk.Label(editor, text=label).pack(anchor='w')
            entry = ttk.Entry(editor)
            entry.insert(0, default)
            entry.pack(fill='x')
            self.fields[label] = entry
        ttk.Label(editor, text='Продукты: название; количество; единица (каждый с новой строки)').pack(anchor='w')
        self.ingredients = tk.Text(editor, height=7)
        self.ingredients.pack(fill='x')
        ttk.Label(editor, text='Приготовление / текст из Word — перенесите один рецепт в поля выше и проверьте порции и калории').pack(anchor='w')
        self.method = tk.Text(editor, height=12)
        self.method.pack(fill='both', expand=True)
        ttk.Button(editor, text='Загрузить текст Word (.docx)', command=self.import_word).pack(side='left')
        ttk.Button(editor, text='Сохранить рецепт', command=self.save_recipe).pack(side='left')
        self.count = ttk.Label(editor, text=f'Рецептов: {len(self.recipes)}')
        self.count.pack(side='left', padx=15)
        self.settings = {}
        for label, default in [('Человек', '2'), ('Порций на человека за приём пищи', '1'), ('Ккал на человека в сутки', '2000'), ('Допуск ± ккал', '200'), ('Исключить продукты (через запятую)', ''), ('Использовать за неделю (через запятую)', '')]:
            ttk.Label(planner, text=label).pack(anchor='w')
            entry = ttk.Entry(planner)
            entry.insert(0, default)
            entry.pack(fill='x')
            self.settings[label] = entry
        ttk.Label(planner, text='3 приёма пищи в день. Пожелания обязательны: каждый продукт хотя бы в одном блюде за неделю.').pack(anchor='w')
        ttk.Button(planner, text='Составить неделю', command=self.generate).pack(anchor='w')
        ttk.Button(planner, text='Сохранить меню и продукты (.txt)', command=self.export).pack(anchor='w')
        self.output = tk.Text(planner, wrap='word')
        self.output.pack(fill='both', expand=True)

    def import_word(self):
        path = filedialog.askopenfilename(filetypes=[('Word', '*.docx')])
        if path:
            try:
                text = word_text(path)
                self.method.delete('1.0', 'end')
                self.method.insert('1.0', text)
            except Exception as e:
                messagebox.showerror('Ошибка импорта', str(e))

    def save_recipe(self):
        try:
            name, servings, kcal = [v.get().strip() for v in self.fields.values()]
            recipe = Recipe(name, int(servings), float(kcal.replace(',', '.')), ingredients_from_text(self.ingredients.get('1.0', 'end')), self.method.get('1.0', 'end').strip())
            if not name or recipe.servings <= 0 or recipe.kcal <= 0:
                raise ValueError('Укажите название, положительное число порций и ккал')
            if any(r.name.casefold() == name.casefold() for r in self.recipes):
                raise ValueError('Рецепт с таким названием уже сохранён')
            updated = self.recipes + [recipe]
            DATA.parent.mkdir(parents=True, exist_ok=True)
            temporary = DATA.with_suffix('.tmp')
            temporary.write_text(json.dumps([r.to_dict() for r in updated], ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(DATA)
            self.recipes = updated
            self.count.config(text=f'Рецептов: {len(self.recipes)}')
            messagebox.showinfo('Готово', 'Рецепт сохранён')
        except Exception as e:
            messagebox.showerror('Проверьте рецепт', str(e))

    def generate(self):
        try:
            values = [v.get() for v in self.settings.values()]
            people, portions, target, tolerance = int(values[0]), float(values[1]), float(values[2]), float(values[3])
            week = plan(self.recipes, people, portions, target, tolerance, values[4].split(','), values[5].split(','))
            lines, all_items = [], []
            def products(items):
                return '\n'.join(f'  {name}: {amount:g} {unit}' for (name, unit), amount in sorted(totals(items).items()))
            for n, day in enumerate(week, 1):
                lines.append(f'День {n}: {sum(r.kcal for r in day)*portions:g} ккал на человека')
                items = [(r, people * portions) for r in day]
                for meal, item in zip(('Завтрак', 'Обед', 'Ужин'), items):
                    lines.append(f'{meal}: {item[0].name} — {item[1]:g} порций\n{products([item])}')
                lines.append('Всего за день:\n' + products(items) + '\n')
                all_items.extend(items)
            lines.append('ПРОДУКТЫ НА НЕДЕЛЮ:\n' + products(all_items))
            self.output.delete('1.0', 'end')
            self.output.insert('1.0', '\n'.join(lines))
        except Exception as e:
            messagebox.showerror('Не удалось составить меню', str(e))

    def export(self):
        text = self.output.get('1.0', 'end').strip()
        if not text:
            return
        path = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Текст', '*.txt')])
        if path:
            try:
                Path(path).write_text(text, encoding='utf-8-sig')
            except OSError as e:
                messagebox.showerror('Ошибка сохранения', str(e))

if __name__ == '__main__':
    App().mainloop()
