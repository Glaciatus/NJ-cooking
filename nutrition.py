"""Small editable reference table. Values are approximate per 100 g of raw food.

Representative generic USDA FoodData Central foods (https://fdc.nal.usda.gov/).
Not a brand database. Cooking losses and edible yield are not modelled.
"""
from dataclasses import dataclass
import math

KEYS = ('kcal', 'protein', 'fat', 'carbs')
DEFAULT_TARGETS = dict(zip(KEYS, (2000.0, 75.0, 67.0, 275.0)))

@dataclass(frozen=True)
class Food:
    values: tuple
    piece_g: float | None = None
    density: float | None = None

# Exact aliases only: e.g. dry rice must not match boiled rice.
FOODS = {}
def food(names, values, piece_g=None, density=None):
    for name in names.split('|'):
        FOODS[name] = Food(values, piece_g, density)

food('рис|рис сухой|рис белый сухой|rice|uncooked rice', (365, 7.1, .7, 80))
food('гречка|гречневая крупа', (343, 13.3, 3.4, 71.5))
food('овсяные хлопья|овсянка|oats|rolled oats', (379, 13.2, 6.5, 67.7))
food('макароны|паста сухая|pasta', (371, 13, 1.5, 74.7))
food('куриная грудка|куриное филе|chicken breast', (120, 22.5, 2.6, 0))
food('индейка филе|филе индейки', (114, 23.7, 1.5, 0))
food('говядина', (187, 20, 12, 0))
food('лосось|salmon', (208, 20.4, 13.4, 0))
food('треска|cod', (82, 17.8, .7, 0))
food('яйцо|яйца|яйцо куриное|egg|eggs', (143, 12.6, 9.5, .7), piece_g=50)
food('молоко|молоко 2.5%|milk', (52, 3, 2.5, 4.8), density=1.03)
food('творог 5%|творог', (121, 17.2, 5, 1.8))
food('йогурт натуральный|plain yogurt', (61, 3.5, 3.3, 4.7), density=1.03)
food('сыр', (350, 25, 27, 0))
food('масло сливочное|сливочное масло|butter', (717, .9, 81.1, .1))
food('масло оливковое|оливковое масло|olive oil', (884, 0, 100, 0), density=.91)
food('масло растительное|растительное масло|подсолнечное масло|vegetable oil', (884, 0, 100, 0), density=.92)
food('картофель|картошка|potato|potatoes', (77, 2, .1, 17.5))
food('морковь|carrot|carrots', (41, .9, .2, 9.6))
food('лук|лук репчатый|onion', (40, 1.1, .1, 9.3))
food('помидор|помидоры|томат|tomato|tomatoes', (18, .9, .2, 3.9))
food('огурец|огурцы|cucumber', (15, .7, .1, 3.6))
food('капуста|cabbage', (25, 1.3, .1, 5.8))
food('брокколи|broccoli', (34, 2.8, .4, 6.6))
food('кабачок|кабачки|zucchini', (17, 1.2, .3, 3.1))
food('банан|бананы|banana', (89, 1.1, .3, 22.8), piece_g=118)
food('яблоко|яблоки|apple', (52, .3, .2, 13.8), piece_g=182)
food('мука|мука пшеничная|flour', (364, 10.3, 1, 76.3))
food('сахар|sugar', (387, 0, 0, 100))
food('хлеб|хлеб пшеничный|bread', (265, 9, 3.2, 49))
food('чечевица|чечевица сухая|lentils', (352, 24.6, 1.1, 63.4))
food('фасоль сухая', (333, 23.6, .8, 60))
food('вода|water|соль|salt', (0, 0, 0, 0), density=1)


def normalize(name):
    return ' '.join(name.casefold().replace('ё', 'е').split())


def number(text, label, *, default=None, minimum=0, integer=False, allow_zero=True):
    """Friendly validation shared by UI/import/model. Never accepts NaN or infinity."""
    if text is None or str(text).strip() == '':
        return default
    try:
        value = float(str(text).strip().replace(',', '.'))
    except (ValueError, TypeError):
        raise ValueError(f'{label}: введите число, например 2 или 2,5.') from None
    if not math.isfinite(value) or value < minimum or (not allow_zero and value == 0):
        raise ValueError(f'{label}: требуется конечное число {"больше" if not allow_zero else "не меньше"} {minimum:g}.')
    if integer and not value.is_integer():
        raise ValueError(f'{label}: введите целое число.')
    return int(value) if integer else value


def ingredient_nutrition(ingredient):
    reference = FOODS.get(normalize(ingredient.name))
    values = ingredient.per100g if ingredient.per100g is not None else (reference.values if reference else None)
    if values is None or ingredient.amount is None or ingredient.amount <= 0:
        return None
    unit = normalize(ingredient.unit).rstrip('.')
    factors = {'г': 1, 'g': 1, 'гр': 1, 'кг': 1000, 'kg': 1000}
    factor = factors.get(unit)
    if factor is None and unit in ('шт', 'pcs', 'piece', 'pieces'):
        factor = ingredient.grams_per_unit or (reference.piece_g if reference else None)
    if factor is None and unit in ('мл', 'ml', 'л', 'l'):
        density = ingredient.grams_per_unit or (reference.density if reference else None)
        factor = density * (1000 if unit in ('л', 'l') else 1) if density else None
    if factor is None:
        return None
    return dict(zip(KEYS, (float(v) * ingredient.amount * factor / 100 for v in values)))


def recipe_nutrition(recipe):
    """Returns per-serving values and names of estimated fields; unknown stays None."""
    explicit = {key: getattr(recipe, key) for key in KEYS}
    estimated = set()
    parts = [ingredient_nutrition(i) for i in recipe.ingredients]
    if recipe.servings and parts and all(p is not None for p in parts):
        for key in KEYS:
            if explicit[key] is None:
                explicit[key] = sum(p[key] for p in parts) / recipe.servings
                estimated.add(key)
    # If all macros were entered, energy can be estimated even without a food match.
    if explicit['kcal'] is None and all(explicit[k] is not None for k in KEYS[1:]):
        explicit['kcal'] = 4 * explicit['protein'] + 9 * explicit['fat'] + 4 * explicit['carbs']
        estimated.add('kcal')
    return explicit, estimated


def nutrition_totals(items):
    result = dict.fromkeys(KEYS, 0.0)
    for recipe, portions in items:
        values, _ = recipe_nutrition(recipe)
        for key in KEYS:
            result[key] = (result[key] + values[key] * portions
                           if result[key] is not None and values[key] is not None else None)
    return result


def nutrition_text(values):
    def fmt(key):
        return 'неизвестно' if values[key] is None else f'{values[key]:.0f}'
    return f'{fmt("kcal")} ккал · Б {fmt("protein")} г · Ж {fmt("fat")} г · У {fmt("carbs")} г'
