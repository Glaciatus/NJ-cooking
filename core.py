"""Local recipe storage, Word import and weekly planning. No external dependencies."""
from dataclasses import dataclass, asdict
from collections import defaultdict
import random
import re
import zipfile
import xml.etree.ElementTree as ET

@dataclass
class Ingredient:
    name: str
    amount: float
    unit: str

@dataclass
class Recipe:
    name: str
    servings: int
    kcal: float  # kcal per serving, confirmed by user
    ingredients: list
    method: str = ''

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, 'ingredients': [Ingredient(**i) for i in data['ingredients']]})


def ingredients_from_text(text):
    result = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(';')]
        if len(parts) != 3 or not parts[0] or not parts[2]:
            raise ValueError('Продукт: название; количество; единица')
        amount = float(parts[1].replace(',', '.'))
        if amount <= 0:
            raise ValueError('Количество продукта должно быть больше нуля')
        result.append(Ingredient(parts[0], amount, parts[2]))
    if not result:
        raise ValueError('Добавьте хотя бы один продукт')
    return result


def word_text(path):
    with zipfile.ZipFile(path) as document:
        root = ET.fromstring(document.read('word/document.xml'))
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    return '\n'.join(
        ''.join(t.text or '' for t in p.findall('.//w:t', ns))
        for p in root.findall('.//w:p', ns))


def totals(items):
    """items: pairs of recipe and requested portions. Units only converted exactly."""
    amounts = defaultdict(float)
    conversion = {'кг': ('г', 1000), 'л': ('мл', 1000)}
    for recipe, portions in items:
        for ingredient in recipe.ingredients:
            unit = ingredient.unit.casefold().strip()
            unit, multiplier = conversion.get(unit, (unit, 1))
            amounts[(ingredient.name.casefold().strip(), unit)] += ingredient.amount * portions / recipe.servings * multiplier
    return dict(amounts)


def plan(recipes, people, portions, target, tolerance, excluded=(), wanted=(), seed=None):
    """Three meals/day; calories per person/day; requested portions per person/meal."""
    if people < 1 or portions <= 0 or target <= 0 or tolerance < 0:
        raise ValueError('Проверьте число людей, порции и калории')
    excluded = [x.strip().casefold() for x in excluded if x.strip()]
    wanted = [x.strip().casefold() for x in wanted if x.strip()]
    def contains(recipe, term):
        return any(term in i.name.casefold() for i in recipe.ingredients)
    eligible = [r for r in recipes if r.servings > 0 and r.kcal > 0 and not any(contains(r, x) for x in excluded)]
    if not eligible:
        raise ValueError('Нет подходящих рецептов с подтверждёнными порциями и калориями')
    for term in wanted:
        if not any(contains(r, term) for r in eligible):
            raise ValueError('Нет подходящего рецепта для пожелания: ' + term)
    rng = random.Random(seed)
    # A bounded search reports failure honestly; it never silently relaxes restrictions.
    candidates = []
    for _ in range(20000):
        day = tuple(rng.choice(eligible) for _ in range(3))
        kcal = sum(r.kcal for r in day) * portions
        if abs(kcal - target) <= tolerance:
            candidates.append(day)
        if len(candidates) >= 2000:
            break
    if not candidates:
        raise ValueError('Подбор не нашёл день в заданной вилке калорий. Добавьте рецепты или расширьте вилку.')
    for _ in range(3000):
        week = [rng.choice(candidates) for _ in range(7)]
        if all(any(contains(r, term) for day in week for r in day) for term in wanted):
            return week
    raise ValueError('Не удалось совместить пожелания с калориями. Попробуйте другие параметры.')
