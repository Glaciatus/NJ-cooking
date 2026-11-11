"""USDA-backed offline nutrients with explicit aliases and editable mass assumptions.

Representative generic USDA FoodData Central foods (https://fdc.nal.usda.gov/).
Not a brand database. Cooking losses and edible yield are not modelled.
"""
from dataclasses import dataclass
from functools import lru_cache
import re
from catalog import records, aliases
import math

KEYS = ('kcal', 'protein', 'fat', 'carbs')
DEFAULT_TARGETS = dict(zip(KEYS, (2000.0, 75.0, 67.0, 275.0)))

@dataclass(frozen=True)
class Food:
    values: tuple
    piece_g: float | None = None
    density: float | None = None
    fdc_id: int | None = None
    description: str = ""
    measures: tuple = ()

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
food('кефир', (53, 3, 2.5, 4), density=1.03)
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


@lru_cache(maxsize=4096)
def reference_food(name, fdc_id=None):
    alias=aliases().get(normalize(name))
    if fdc_id and alias and alias['fdc_id']!=fdc_id:alias=None
    identifier=fdc_id or (alias['fdc_id'] if alias else None)
    if identifier:
        record=records().get(identifier)
        if record:
            piece=alias.get('piece_g') if alias else None
            if piece:
                options=[m['grams'] for m in record['measures'] if any(w in m['label'].casefold() for w in ('medium','large','small','clove','egg'))
                         and not any(w in m['label'].casefold() for w in ('slice','chopped','cup','extra','jumbo'))]
                if options:piece=min(options,key=lambda g:abs(g-piece))
            return Food(tuple(record['values']),
                        piece,
                        alias.get('density') if alias else None,
                        identifier,record['description'],tuple((m['label'],m['grams']) for m in record['measures']))
    if fdc_id:return None
    return FOODS.get(normalize(name))


def ingredient_amount(ingredient):
    return ingredient.amount if ingredient.amount is not None else ingredient.amount_estimate


def ingredient_mass(ingredient):
    reference=reference_food(ingredient.name,ingredient.fdc_id)
    amount=ingredient_amount(ingredient)
    if amount is None:return None
    unit=normalize(ingredient.unit).rstrip('.')
    factors={'г':1,'g':1,'гр':1,'кг':1000,'kg':1000}
    factor=factors.get(unit)
    measures=dict(reference.measures) if reference else {}
    if factor is None and unit in ('шт','pcs','piece','pieces','головка','головки','зубчик','зубчика','зубчиков'):
        # A garlic head and a clove must not share the same mass.
        special=120 if 'лук' in normalize(ingredient.name) and unit.startswith('голов') else (40 if 'чеснок' in normalize(ingredient.name) and unit.startswith('голов') else None)
        factor=ingredient.grams_per_unit or special or (reference.piece_g if reference else None)
        if factor is None:
            candidates=[g for label,g in measures.items() if any(x in label.casefold() for x in ('medium','large egg','clove')) and not any(x in label.casefold() for x in ('slice','chopped','cup'))]
            factor=candidates[0] if candidates else None
    density=ingredient.grams_per_unit if unit in ('мл','ml','л','l') else None
    density=density or (reference.density if reference else None)
    if density is None:
        cups=[g for label,g in measures.items() if label.strip().casefold() in ('cup','cup, chopped','cup, diced','cup, sliced','cup, sifted','cup, unsifted','cup, melted')]
        density=cups[0]/236.588 if cups else None
    if factor is None and unit in ('мл','ml','л','l') and density:
        factor=density*(1000 if unit in ('л','l') else 1)
    volumes={'ст. л':15,'ст.л':15,'столовая ложка':15,'tbsp':15,'ч. л':5,'ч.л':5,'tsp':5,
             'стакан':250,'стакана':250,'стаканов':250,'cup':236.588,'cups':236.588}
    if factor is None and unit in volumes:
        needle='tablespoon' if volumes[unit]==15 else 'teaspoon' if volumes[unit]==5 else 'cup'
        short='tbsp' if needle=='tablespoon' else 'tsp' if needle=='teaspoon' else 'cup'
        direct=[g for label,g in measures.items() if label.strip().casefold()==needle or label.strip().casefold()==short or label.strip().casefold().startswith(short+',')]
        factor=(direct[0]*(volumes[unit]/236.588 if needle=='cup' else 1) if direct else density*volumes[unit] if density else None)
    if factor is None and unit in ('щепотка','щепотки'):
        factor=.3  # explicit average; always marked as an estimate in reports
    if factor is None and unit in ('пучок','пучка'):
        factor=30
    if factor is None and unit in ('пакетик','пакетика','пакетиков'):
        name=normalize(ingredient.name)
        factor=7 if 'дрожж' in name else 8 if 'ванильный сахар' in name or 'сахар ванильный' in name else 10 if 'разрыхлитель' in name else None
    if factor is None and unit in ('банка','банки') and 'сгущ' in normalize(ingredient.name):
        factor=380
    if factor is None and unit in ('горсть','горсти'):
        factor=20
    if factor is None and unit in ('веточка','веточки'):
        factor=2
    return amount*factor if factor is not None else None


def ingredient_nutrition(ingredient):
    reference=reference_food(ingredient.name,ingredient.fdc_id)
    values=ingredient.per100g if ingredient.per100g is not None else (reference.values if reference else None)
    mass=ingredient_mass(ingredient)
    if values is None or mass is None:return None
    return dict(zip(KEYS,(float(v)*mass/100 if v is not None else None for v in values)))


def recipe_nutrition(recipe):
    """Returns per-serving values and names of estimated fields; unknown stays None."""
    explicit = {key: getattr(recipe, key) for key in KEYS}
    estimated = set()
    from estimation import servings_info
    servings=servings_info(recipe).servings
    parts = [ingredient_nutrition(i) for i in recipe.ingredients]
    if servings and parts:
        for key in KEYS:
            if explicit[key] is None and all(p is not None and p[key] is not None for p in parts):
                explicit[key] = sum(p[key] for p in parts) / servings
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

# USDA provenance is retained on each automatically matched food.
for _alias in aliases():
    FOODS[_alias] = reference_food(_alias)
