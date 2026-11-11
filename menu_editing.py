"""Non-mutating manual edits to the 7×3 arrangement; nutrition is always derived."""
from collections import Counter
from core import MEALS,recipe_key,contains
from estimation import servings_info
from tagging import recipe_tags

TIMES=('Утро · завтрак','День · обед','Вечер · ужин')

def slot_index(slot):
    day,meal=slot
    if type(day) is not int or type(meal) is not int or not 0<=day<7 or not 0<=meal<3:
        raise ValueError('Выберите день 1–7 и один из трёх приёмов пищи.')
    return day*3+meal

def flatten(week):
    if len(week)!=7 or any(len(day)!=3 for day in week):raise ValueError('В меню должно быть 7 дней по 3 блюда.')
    return [r for day in week for r in day]

def arrange(items):return [tuple(items[d*3:d*3+3]) for d in range(7)]

def replace_dish(week,slot,recipe):
    items=flatten(week);items[slot_index(slot)]=recipe;return arrange(items)

def swap_dishes(week,source,target):
    items=flatten(week);a,b=slot_index(source),slot_index(target)
    items[a],items[b]=items[b],items[a];return arrange(items)

def move_dish(week,source,target):
    items=flatten(week);a,b=slot_index(source),slot_index(target)
    recipe=items.pop(a);items.insert(b,recipe);return arrange(items)

def arrangement_warnings(week,context,enabled_databases=None):
    warnings=[];items=flatten(week);present={recipe_key(r) for r in items}
    missing=set(context.get('required_ids',[]))-present
    if missing:warnings.append('Удалены обязательные блюда: '+', '.join(context.get('required_names',{}).get(k,k) for k in sorted(missing)))
    counts=Counter(r.database_id for r in items)
    for db,quota in context.get('database_limits',{}).items():
        if counts[db]!=quota:warnings.append(f'Количество блюд из базы {context.get("database_names",{}).get(db,db)}: {counts[db]}, было задано {quota}.')
    excluded=[x.strip() for x in context.get('excluded',[]) if x.strip()]
    wanted=[x.strip() for x in context.get('wanted',[]) if x.strip()]
    for term in wanted:
        if not any(contains(r,term) for r in items):warnings.append('Не использован желаемый продукт: '+term)
    for day,recipes in enumerate(week):
        for meal,r in enumerate(recipes):
            where=f'День {day+1}, {MEALS[meal]}: «{r.name}»'
            if r.meal not in ('Любой',MEALS[meal]):warnings.append(where+' — в карточке указано «'+r.meal+'».')
            forbidden=[x for x in excluded if contains(r,x)]
            if forbidden:warnings.append(where+' — исключённые продукты: '+', '.join(forbidden))
            if not servings_info(r).servings:warnings.append(where+' — выход неизвестен; покупки нельзя полностью пересчитать.')
            if enabled_databases is not None and r.database_id not in enabled_databases:warnings.append(where+' — база сейчас отключена.')
            if context.get('desired_tags') and recipe_key(r) not in context.get('required_ids',[]) and not set(recipe_tags(r)).intersection(context['desired_tags']):
                warnings.append(where+' — не совпадает с выбранными типами блюд.')
    return list(dict.fromkeys(warnings))
