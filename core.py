"""Validated recipes, Word extraction, ingredient totals and constrained weekly menus."""
from dataclasses import dataclass, asdict, field
from collections import defaultdict, Counter
from itertools import product
import random
import zipfile
import xml.etree.ElementTree as ET
from nutrition import KEYS, DEFAULT_TARGETS, number, normalize, recipe_nutrition, nutrition_text

MEALS = ('Завтрак', 'Обед', 'Ужин')

@dataclass
class Ingredient:
    name: str
    amount: float | None
    unit: str
    per100g: list | None = None
    grams_per_unit: float | None = None
    original: str = ''

@dataclass
class Recipe:
    name: str
    servings: float | None
    kcal: float | None
    ingredients: list
    method: str = ''
    protein: float | None = None
    fat: float | None = None
    carbs: float | None = None
    source_url: str = ''
    meal: str = 'Любой'
    import_notes: list = field(default_factory=list)
    reviewed: bool = True

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        result = cls(**{**data, 'ingredients': [Ingredient(**i) for i in data['ingredients']]})
        validate_recipe(result)
        return result


def validate_recipe(recipe):
    if not recipe.name.strip():
        raise ValueError('Укажите название рецепта.')
    recipe.servings = number(recipe.servings, 'Порции', allow_zero=False)
    if recipe.meal not in ('Любой', *MEALS):
        raise ValueError('Выберите приём пищи из списка.')
    for key in KEYS:
        setattr(recipe, key, number(getattr(recipe, key), key))
    for i in recipe.ingredients:
        if not i.name.strip():
            raise ValueError('У каждого продукта должно быть название.')
        i.amount = number(i.amount, f'Количество «{i.name}»', allow_zero=False)
        if i.per100g is not None:
            if len(i.per100g) != 4:
                raise ValueError('КБЖУ продукта: нужны четыре значения на 100 г.')
            i.per100g = [number(v, 'КБЖУ продукта') for v in i.per100g]
            if any(v is None for v in i.per100g):
                raise ValueError('Заполните все четыре значения КБЖУ продукта или оставьте все пустыми.')
        i.grams_per_unit = number(i.grams_per_unit, 'Масса единицы', allow_zero=False)


def readiness(recipe):
    reasons = []
    if not recipe.reviewed:
        reasons.append('проверьте импорт и сохраните рецепт')
    if not recipe.servings:
        reasons.append('укажите исходное число порций')
    if not recipe.ingredients:
        reasons.append('добавьте продукты')
    if any(i.amount is None or not i.unit for i in recipe.ingredients):
        reasons.append('уточните количество и единицы продуктов')
    values, _ = recipe_nutrition(recipe)
    missing = [name for key, name in zip(KEYS, ('калории', 'белки', 'жиры', 'углеводы')) if values[key] is None]
    if missing:
        reasons.append('дополните КБЖУ: ' + ', '.join(missing))
    if values['kcal'] == 0:
        reasons.append('нулевая калорийность: проверьте состав')
    return reasons


def ingredients_from_text(text):
    result = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(';')]
        if len(parts) != 3 or not parts[0] or not parts[2]:
            raise ValueError(f'Строка {n}: используйте «название; количество; единица».')
        result.append(Ingredient(parts[0], number(parts[1], 'Количество', allow_zero=False), parts[2]))
    if not result:
        raise ValueError('Добавьте хотя бы один продукт.')
    return result


def word_text(path):
    with zipfile.ZipFile(path) as document:
        if document.getinfo('word/document.xml').file_size > 10_000_000:
            raise ValueError('Документ слишком большой (максимум 10 МБ текста).')
        root = ET.fromstring(document.read('word/document.xml'))
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    return '\n'.join(''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in root.findall('.//w:p', ns))


def totals(items):
    amounts = defaultdict(float)
    conversion = {'кг': ('г', 1000), 'kg': ('г', 1000), 'g': ('г', 1), 'гр': ('г', 1),
                  'л': ('мл', 1000), 'l': ('мл', 1000), 'ml': ('мл', 1)}
    for recipe, portions in items:
        if not recipe.servings:
            raise ValueError(f'«{recipe.name}»: укажите число порций для пересчёта.')
        for ingredient in recipe.ingredients:
            if ingredient.amount is None or not ingredient.unit:
                raise ValueError(f'«{ingredient.name}»: уточните количество и единицу.')
            unit = normalize(ingredient.unit).rstrip('.')
            unit, multiplier = conversion.get(unit, (unit, 1))
            amounts[(normalize(ingredient.name), unit)] += ingredient.amount * portions / recipe.servings * multiplier
    return dict(amounts)


def contains(recipe, term):
    return any(normalize(term) in normalize(i.name) for i in recipe.ingredients)


def plan(recipes, people=2, portions=1, target=None, tolerance=None, excluded=(), wanted=(), seed=None,
         macro_targets=None, macro_tolerance=.2):
    """Three meals/day. All targets per person/day; unknown nutrition is not zero.

    Exhaustive day search up to 100k combinations, bounded sample beyond that.
    Every returned day respects all four nutrient bounds and every wish is covered.
    """
    people = number(people, 'Человек', default=2, integer=True, allow_zero=False)
    portions = number(portions, 'Порции', default=1, allow_zero=False)
    target = number(target, 'Калории', default=DEFAULT_TARGETS['kcal'], allow_zero=False)
    tolerance = number(tolerance, 'Допуск калорий', default=200)
    if not 0 <= macro_tolerance <= 1:
        raise ValueError('Допуск БЖУ должен быть от 0 до 100%.')
    targets = {**DEFAULT_TARGETS, 'kcal': target}
    for key, value in (macro_targets or {}).items():
        if key in KEYS[1:]:
            targets[key] = number(value, key, default=DEFAULT_TARGETS[key], allow_zero=False)
    bounds = {'kcal': tolerance, **{k: targets[k] * macro_tolerance for k in KEYS[1:]}}
    excluded = [normalize(x) for x in excluded if x.strip()]
    wanted = list(dict.fromkeys(normalize(x) for x in wanted if x.strip()))
    eligible = [r for r in recipes if not readiness(r) and not any(contains(r, x) for x in excluded)]
    if not eligible:
        raise ValueError('Нет готовых рецептов для меню. На шаге 1 проверьте статусы рецептов, порции, продукты и КБЖУ. Также проверьте исключения.')
    for term in wanted:
        if not any(contains(r, term) for r in eligible):
            raise ValueError(f'Для пожелания «{term}» нет готового рецепта без исключённых продуктов. Добавьте рецепт или измените пожелание.')
    slots = [[n for n, r in enumerate(eligible) if r.meal in ('Любой', meal)] for meal in MEALS]
    for meal, choices in zip(MEALS, slots):
        if not choices:
            raise ValueError(f'Нет готовых рецептов для приёма пищи «{meal}». Измените категорию или добавьте рецепт.')
    values = [recipe_nutrition(r)[0] for r in eligible]
    rng = random.Random(seed)
    count = len(slots[0]) * len(slots[1]) * len(slots[2])
    exhaustive = count <= 100_000
    combinations = product(*slots) if exhaustive else (tuple(rng.choice(slot) for slot in slots) for _ in range(60_000))
    candidates = []
    closest = None
    best_error = float('inf')
    seen = set()
    for day in combinations:
        if day in seen:
            continue
        seen.add(day)
        daily = {k: sum(values[n][k] for n in day) * portions for k in KEYS}
        error = sum(abs(daily[k] - targets[k]) / max(targets[k], 1) for k in KEYS)
        if error < best_error:
            closest, best_error = daily, error
        if all(abs(daily[k] - targets[k]) <= bounds[k] + 1e-8 for k in KEYS):
            cover = frozenset(t for t in wanted if any(contains(eligible[n], t) for n in day))
            candidates.append((day, cover, error))
    if not candidates:
        prefix = 'Нет сочетания' if exhaustive else 'Ограниченный поиск не нашёл сочетания'
        raise ValueError(f'{prefix} в заданных пределах КБЖУ. Ближайший найденный день: {nutrition_text(closest)}. Цель: {nutrition_text(targets)}. Добавьте рецепты, измените порции или увеличьте допуски.')
    for term in wanted:
        if not any(term in c[1] for c in candidates):
            raise ValueError(f'Рецепты с «{term}» не вписываются в суточное КБЖУ. Измените цели, допуски или состав рецептов.')
    # A wish-aware greedy cover with randomised retries; diversification penalises repetition.
    pool = candidates if len(candidates) <= 2000 else rng.sample(candidates, 2000)
    for term in wanted:
        pool.append(next(c for c in candidates if term in c[1]))
    for _ in range(100):
        uncovered, usage, week = set(wanted), Counter(), []
        for _day in range(7):
            ranked = []
            for candidate in pool:
                day, cover, error = candidate
                score = (-1000 * len(cover & uncovered) + sum(usage[n] * 2 for n in day)
                         + (3 - len(set(day))) * 3 + error + rng.random() * 2)
                ranked.append((score, candidate))
            _, (day, cover, _) = min(ranked, key=lambda x: x[0])
            week.append(tuple(eligible[n] for n in day))
            uncovered -= cover
            usage.update(day)
        if not uncovered:
            return week
    raise ValueError('Не удалось включить все пожелания в семь дней. Сократите список пожеланий или добавьте рецепты с несколькими желаемыми продуктами.')
