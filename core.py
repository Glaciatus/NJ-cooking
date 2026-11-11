"""Validated recipes, Word extraction, ingredient totals and constrained weekly menus."""
from dataclasses import dataclass, asdict, field
from collections import defaultdict, Counter
from itertools import product, chain
import random
import logging
from constrained_search import anchored_days,anchor_diagnostic

log=logging.getLogger("nj_cooking.planner")
import uuid
import zipfile
import xml.etree.ElementTree as ET
from nutrition import KEYS, DEFAULT_TARGETS, number, normalize, recipe_nutrition, nutrition_text, ingredient_amount
from estimation import servings_info
from tagging import TAGS, recipe_tags

MEALS = ('Завтрак', 'Обед', 'Ужин')

@dataclass
class Ingredient:
    name: str
    amount: float | None
    unit: str
    per100g: list | None = None
    grams_per_unit: float | None = None
    original: str = ''
    fdc_id: int | None = None
    amount_estimate: float | None = None
    amount_basis: str = ''

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
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)
    tags: list | None = None
    source_category: str = ''
    database_id: str = ''
    image_url: str = ''
    video_url: str = ''
    source_nutrition_per100g: dict | None = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data.setdefault('uid', uuid.uuid5(uuid.NAMESPACE_URL, data.get('source_url') or data.get('name','')).hex)
        result = cls(**{**data, 'ingredients': [Ingredient(**i) for i in data['ingredients']]})
        validate_recipe(result)
        return result


def validate_recipe(recipe):
    if not recipe.name.strip():
        raise ValueError('Укажите название рецепта.')
    recipe.servings = number(recipe.servings, 'Порции', allow_zero=False)
    if recipe.meal not in ('Любой', *MEALS):
        raise ValueError('Выберите приём пищи из списка.')
    if recipe.tags is not None and (not isinstance(recipe.tags,list) or any(t not in TAGS for t in recipe.tags)):
        raise ValueError('Неизвестная принадлежность рецепта.')
    if not isinstance(recipe.uid,str) or not recipe.uid:
        raise ValueError('Рецепт должен иметь идентификатор.')
    if recipe.source_nutrition_per100g is not None:
        if not isinstance(recipe.source_nutrition_per100g,dict) or any(k not in KEYS for k in recipe.source_nutrition_per100g):
            raise ValueError('Неверные исходные данные КБЖУ на 100 г.')
        recipe.source_nutrition_per100g={k:number(recipe.source_nutrition_per100g.get(k),k) for k in KEYS}
    for key in KEYS:
        setattr(recipe, key, number(getattr(recipe, key), key))
    for i in recipe.ingredients:
        if not i.name.strip():
            raise ValueError('У каждого продукта должно быть название.')
        i.amount_estimate = number(i.amount_estimate, 'Оценка количества', allow_zero=False)
        if i.fdc_id is not None:
            i.fdc_id=number(i.fdc_id,'USDA FDC ID',integer=True,allow_zero=False)
        i.amount = number(i.amount, f'Количество «{i.name}»', allow_zero=False)
        if i.per100g is not None:
            if len(i.per100g) != 4:
                raise ValueError('КБЖУ продукта: нужны четыре значения на 100 г.')
            i.per100g = [number(v, 'КБЖУ продукта') for v in i.per100g]
            if any(v is None for v in i.per100g):
                raise ValueError('Заполните все четыре значения КБЖУ продукта или оставьте все пустыми.')
        i.grams_per_unit = number(i.grams_per_unit, 'Масса единицы', allow_zero=False)


def readiness(recipe, require_nutrition=True):
    reasons=[]
    if not servings_info(recipe).servings:reasons.append('укажите число порций: автоматическая оценка невозможна')
    if not recipe.ingredients:reasons.append('добавьте продукты')
    if require_nutrition:
        values,_=recipe_nutrition(recipe)
        missing=[name for key,name in zip(KEYS,('калории','белки','жиры','углеводы')) if values[key] is None]
        if missing:reasons.append('дополните КБЖУ: '+', '.join(missing))
        if values['kcal']==0:reasons.append('нулевая калорийность: проверьте состав')
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


def totals(items, allow_unknown=False):
    amounts = defaultdict(float)
    conversion = {'кг': ('г', 1000), 'kg': ('г', 1000), 'g': ('г', 1), 'гр': ('г', 1),
                  'л': ('мл', 1000), 'l': ('мл', 1000), 'ml': ('мл', 1)}
    for recipe, portions in items:
        servings=servings_info(recipe).servings
        if not servings:
            raise ValueError(f'«{recipe.name}»: укажите число порций для пересчёта.')
        for ingredient in recipe.ingredients:
            amount=ingredient_amount(ingredient)
            if amount is None or not ingredient.unit:
                if allow_unknown:continue
                raise ValueError(f'«{ingredient.name}»: уточните количество и единицу.')
            unit = normalize(ingredient.unit).rstrip('.')
            unit, multiplier = conversion.get(unit, (unit, 1))
            amounts[(normalize(ingredient.name), unit)] += amount * portions / servings * multiplier
    return dict(amounts)


def contains(recipe, term):
    return any(normalize(term) in normalize(i.name) for i in recipe.ingredients)


class NutritionSearchFailure(ValueError):
    """A search failed after hard recipe/quantity checks passed."""


def plan(recipes, people=2, portions=1, target=None, tolerance=None, excluded=(), wanted=(), seed=None,
         macro_targets=None, macro_tolerance=.2, require_nutrition=True, desired_tags=None, required_ids=(), database_limits=None, allow_nutrition_deviations=False):
    """Three meals/day. All targets per person/day; unknown nutrition is not zero.

    Exhaustive day search up to 100k combinations, bounded sample beyond that.
    In strict mode every day respects all nutrient bounds. Every wish is covered.
    """
    log.info('plan_start recipes=%s required=%s strict=%s',len(recipes),len(required_ids),require_nutrition)
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
    limits={db:number(value,'Количество блюд из базы',integer=True,allow_zero=True) for db,value in (database_limits or {}).items()}
    if any(v is None or v>21 for v in limits.values()) or sum(limits.values())>21:
        raise ValueError('Квоты баз: целые числа от 0 до 21, сумма не больше 21.')
    keys={recipe_key(r):r for r in recipes}
    required=set()
    for identifier in required_ids:
        if identifier not in keys:
            matches=[key for key,r in keys.items() if r.uid==identifier]
            if len(matches)!=1:raise ValueError('Обязательный рецепт отсутствует в подключённых базах: '+str(identifier))
            identifier=matches[0]
        required.add(identifier)
    if len(required)>21:raise ValueError('Отмечено больше 21 обязательного рецепта: в неделе только 21 место.')
    def rejection_reasons(recipe):
        reasons=readiness(recipe,require_nutrition)
        if limits.get(recipe.database_id,1)==0:reasons.append('для базы задано 0 блюд за неделю')
        if recipe_key(recipe) not in required and desired_tags and not set(desired_tags).intersection(recipe_tags(recipe)):
            reasons.append('не совпадает с выбранными типами блюд')
        forbidden=[term for term in excluded if contains(recipe,term)]
        if forbidden:reasons.append('содержит исключённые продукты: '+', '.join(forbidden))
        return reasons
    rejected={recipe_key(r):rejection_reasons(r) for r in recipes}
    eligible=[r for r in recipes if not rejected[recipe_key(r)]]
    blocked=required-{recipe_key(r) for r in eligible}
    if blocked:
        details=['«'+keys[k].name+'»: '+'; '.join(rejected[k])+'.' for k in sorted(blocked)]
        raise ValueError('Обязательные рецепты нельзя включить:\n'+'\n'.join(details))
    if not eligible:
        raise ValueError('Нет готовых рецептов для меню. Проверьте включённые базы, теги, исключения и выход рецептов. Для неполного КБЖУ отключите обязательную проверку.')
    for term in wanted:
        if not any(contains(r,term) for r in eligible):raise ValueError(f'Для пожелания «{term}» нет готового рецепта без исключённых продуктов.')
    slots=[[n for n,r in enumerate(eligible) if r.meal in ('Любой',meal)] for meal in MEALS]
    for meal,choices in zip(MEALS,slots):
        if not choices:raise ValueError(f'Нет готовых рецептов для «{meal}». Расширьте набор баз, тегов или категории блюд.')
    active_dbs={r.database_id for r in eligible}
    if active_dbs<=limits.keys() and sum(limits.get(db,0) for db in active_dbs)!=21:
        raise ValueError('Если число блюд задано для всех доступных баз, сумма должна быть 21.')
    capacities={db:sum(any(eligible[n].database_id==db for n in slot) for slot in slots) for db in limits}
    minima={db:sum(all(eligible[n].database_id==db for n in slot) for slot in slots) for db in limits}
    for db,quota in limits.items():
        if not minima[db]*7<=quota<=capacities[db]*7:raise ValueError('Квота базы несовместима с доступными завтраками, обедами и ужинами: '+db)
        if sum(keys[k].database_id==db for k in required)>quota:raise ValueError('Обязательных рецептов больше, чем квота базы: '+db)
    if sum(keys[k].database_id not in limits for k in required)>21-sum(limits.values()):
        raise ValueError('После заданных квот не остаётся мест для обязательных рецептов из других баз.')
    for meal,slot in zip(MEALS,slots):
        forced=sum(keys[k].meal==meal for k in required)
        if forced>7:raise ValueError(f'Для «{meal}» отмечено {forced} обязательных рецептов, а мест только 7.')
    tokens={('product',term) for term in wanted}|{('recipe',key) for key in required}
    coverage=[frozenset({('product',t) for t in wanted if contains(r,t)}|({('recipe',recipe_key(r))} if recipe_key(r) in required else set())) for r in eligible]
    log.info('eligible=%s rejected=%s slots=%s quotas=%s',len(eligible),len(rejected)-len(eligible),[len(s) for s in slots],limits)
    values=[recipe_nutrition(r)[0] for r in eligible]
    rng=random.Random(seed)
    count=len(slots[0])*len(slots[1])*len(slots[2])
    exhaustive=count<=100_000
    favourites=[[n for n in slot if recipe_key(eligible[n]) in required] for slot in slots]
    by_db=[{db:[n for n in slot if eligible[n].database_id==db] for db in sorted(active_dbs)} for slot in slots]
    def pick(slot,prefer=False,weighted=False):
        if prefer and favourites[slot] and rng.random()<.75:return rng.choice(favourites[slot])
        if weighted and limits:
            databases=[db for db,choices in by_db[slot].items() if choices]
            spare=max(0,21-sum(limits.values()))
            free=max(1,len(active_dbs-limits.keys()))
            weights=[limits.get(db,spare/free) for db in databases]
            if sum(weights)>0:
                db=rng.choices(databases,weights=weights)[0]
                return rng.choice(by_db[slot][db])
        return rng.choice(slots[slot])
    def targeted():
        if exhaustive:return
        for n,r in enumerate(eligible):
            if recipe_key(r) not in required:continue
            for pos in range(3):
                if n not in slots[pos]:continue
                for _ in range(800):yield tuple(n if j==pos else pick(j,True,True) for j in range(3))
    combinations=product(*slots) if exhaustive else chain((tuple(pick(j,False,True) for j in range(3)) for _ in range(60_000)),targeted())
    candidates=[];closest=None;best_error=float('inf');seen=set()
    for day in combinations:
        if day in seen:continue
        seen.add(day)
        daily={k:sum(values[n][k] for n in day)*portions if all(values[n][k] is not None for n in day) else None for k in KEYS}
        error=sum((max(0,abs(daily[k]-targets[k])-bounds[k])/max(bounds[k],targets[k]*.01,1) if allow_nutrition_deviations else abs(daily[k]-targets[k])/max(targets[k],1)) if daily[k] is not None else .5 for k in KEYS)
        if error<best_error:closest,best_error=daily,error
        if allow_nutrition_deviations or not require_nutrition or all(daily[k] is not None and abs(daily[k]-targets[k])<=bounds[k]+1e-8 for k in KEYS):
            cover=frozenset().union(*(coverage[n] for n in day))
            dbcounts=Counter(eligible[n].database_id for n in day)
            if all(dbcounts[db]<=quota for db,quota in limits.items()):candidates.append((day,cover,error,dbcounts))
    log.info('random_or_exhaustive_days=%s candidates=%s exhaustive=%s',len(seen),len(candidates),exhaustive)
    for token in sorted(tokens):
        if any(token in c[1] for c in candidates):continue
        anchors=[n for n in range(len(eligible)) if token in coverage[n]]
        label=keys[token[1]].name if token[0]=='recipe' else token[1]
        budget=2_000_000;complete=True;added=0
        for fixed in anchors:
            days,finished,checks=anchored_days(fixed,slots,values,eligible,targets,bounds,portions,require_nutrition and not allow_nutrition_deviations,limits,max_checks=budget)
            budget-=checks;complete=complete and finished
            for day in days:
                daily={k:sum(values[n][k] for n in day)*portions if all(values[n][k] is not None for n in day) else None for k in KEYS}
                error=sum((max(0,abs(daily[k]-targets[k])-bounds[k])/max(bounds[k],targets[k]*.01,1) if allow_nutrition_deviations else abs(daily[k]-targets[k])/max(targets[k],1)) if daily[k] is not None else .5 for k in KEYS)
                cover=frozenset().union(*(coverage[n] for n in day))
                candidates.append((day,cover,error,Counter(eligible[n].database_id for n in day)));added+=1
            if added or budget<=0:break
        log.info('anchored_search wish=%r found=%s work_units=%s complete=%s',label,added,2_000_000-budget,complete)
        if not added:
            diagnostic=anchor_diagnostic(anchors[0],slots,values,eligible,targets,bounds,portions,require_nutrition) if anchors else ''
            outcome='Все дневные сочетания проверены, подходящего нет.' if complete and budget>0 else 'В пределах лимита поиска сочетание не найдено; невозможность не доказана.'
            hint='Для подбора без жёстких пределов снимите «Обязательный контроль КБЖУ» на шаге 2. Либо измените цели, допуски, квоты или добавьте другие блюда.' if require_nutrition else 'Контроль КБЖУ уже выключен. Проверьте квоты и доступные приёмы пищи в базах.'
            raise NutritionSearchFailure(f'Не удалось включить «{label}». {outcome}\n'+diagnostic+'\n'+hint)
    if not candidates:
        raise NutritionSearchFailure('Подбор не нашёл сочетания в заданных пределах КБЖУ и квот. Ближайший день: '+nutrition_text(closest or dict.fromkeys(KEYS))+'. Добавьте рецепты или расширьте ограничения.')
    for token in tokens:
        if not any(token in c[1] for c in candidates):
            label=keys[token[1]].name if token[0]=='recipe' else token[1]
            raise ValueError('Обязательное пожелание не вписывается в дневные ограничения: '+label)
    pool=candidates if len(candidates)<=2000 else rng.sample(candidates,2000)
    if allow_nutrition_deviations:
        pool=sorted(candidates,key=lambda c:c[2])[:1000]+pool[:1000]
    for token in sorted(tokens):
        matching=[c for c in candidates if token in c[1]]
        pool.extend(sorted(matching,key=lambda c:(-len(c[1]),c[2]))[:10])
    for _ in range(200 if limits or required else 100):
        uncovered=set(tokens);usage=Counter();week=[];remaining=dict(limits)
        for day_number in range(7):
            days_left=6-day_number
            ranked=[]
            for candidate in pool:
                day,cover,error,dbcounts=candidate
                if any(not minima[db]*days_left<=remaining[db]-dbcounts[db]<=capacities[db]*days_left for db in limits):continue
                if sum(remaining[db]-dbcounts[db] for db in limits)>days_left*3:continue
                needed=uncovered-cover
                if sum(t[0]=='recipe' for t in needed)>days_left*3:continue
                if any(sum(t[0]=='recipe' and keys[t[1]].meal==meal for t in needed)>days_left for meal in MEALS):continue
                quota_error=sum(abs(dbcounts[db]-remaining[db]/(days_left+1)) for db in limits)
                score=(-1000*len(cover&uncovered)+sum(usage[n]*2 for n in day)+(3-len(set(day)))*3+error+quota_error*5+rng.random()*3)
                ranked.append((score,candidate))
            if not ranked:break
            _,(day,cover,_,dbcounts)=min(ranked,key=lambda x:x[0])
            week.append(tuple(eligible[n] for n in day));uncovered-=cover;usage.update(day)
            for db in remaining:remaining[db]-=dbcounts[db]
        if len(week)==7 and not uncovered and all(v==0 for v in remaining.values()):
            log.info('plan_success days=7 required_covered=%s',len(required))
            return week
    raise NutritionSearchFailure('Ограниченный подбор не смог совместить обязательные рецепты, квоты баз и остальные условия за 7 дней. Измените отметки, квоты или допуски.')


def recipe_key(recipe):
    return f"{recipe.database_id}:{recipe.uid}" if recipe.database_id else recipe.uid


def refresh_week(week, recipes):
    """Resolve snapshots by stable ID, never by edited name or list position."""
    lookup={recipe_key(r):r for r in recipes}
    missing=[r.name for day in week for r in day if recipe_key(r) not in lookup]
    if missing:raise ValueError('Рецепты удалены из библиотеки: '+', '.join(dict.fromkeys(missing)))
    return [tuple(lookup[recipe_key(r)] for r in day) for day in week]
