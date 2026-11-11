from core import MEALS, totals
from nutrition import KEYS, recipe_nutrition, nutrition_totals, nutrition_text, ingredient_amount
from estimation import servings_info
from tagging import recipe_tags


def products_text(items):
    items=list(items)
    computable=[(r,p) for r,p in items if servings_info(r).servings]
    lines=[f'  {name}: {amount:.1f}'.rstrip('0').rstrip('.')+f' {unit}'
           for (name,unit),amount in sorted(totals(computable,allow_unknown=True).items())]
    unknown=[];assumptions=[]
    for recipe,portions in items:
        if not servings_info(recipe).servings:
            unknown.append(f'«{recipe.name}»: выход неизвестен, продукты не пересчитаны')
            continue
        for i in recipe.ingredients:
            if ingredient_amount(i) is None or not i.unit:
                unknown.append(i.original or i.name+' — количество неизвестно')
            elif i.amount is None and i.amount_estimate is not None:
                assumptions.append(i.name+': '+i.amount_basis)
    if unknown:
        lines.append('  НЕ ВКЛЮЧЕНО В ЧИСЛОВУЮ СУММУ — уточните:')
        lines.extend('    '+x for x in dict.fromkeys(unknown))
    if assumptions:
        lines.append('  ≈ Допущения количества: '+'; '.join(dict.fromkeys(assumptions)))
    return '\n'.join(lines)


def week_issues(week, portions, targets, tolerance, macro_tolerance):
    issues=[]
    for n,day in enumerate(week,1):
        values=nutrition_totals([(r,portions) for r in day])
        if any(v is None for v in values.values()):issues.append(f'День {n}: КБЖУ известно частично.')
        for k in KEYS:
            if values[k] is not None and abs(values[k]-targets[k])>(tolerance if k=='kcal' else targets[k]*macro_tolerance)+1e-8:
                issues.append(f'День {n}: {k} вне заданного допуска.')
    return issues


def week_report(week, people, portions, targets, tolerance, macro_tolerance, require_nutrition=True):
    lines=['МЕНЮ НА НЕДЕЛЮ',f'Человек: {people}; порций на человека за приём пищи: {portions:g}',
           'Цель на человека в сутки: '+nutrition_text(targets),
           f'Допуски: ±{tolerance:g} ккал; БЖУ ±{macro_tolerance*100:g}%.',
           'Контроль КБЖУ: '+('обязательный' if require_nutrition else 'выключен; цели используются только как пожелание'),
           'Разные строки продуктов складываются: граммы + стаканы + ложки; это не варианты замены.\nКБЖУ ниже — на человека, продукты — на всю семью. «≈» — оценка по USDA/справочнику, средним массам и выходу. Неизвестно не означает ноль.\n']
    issues=week_issues(week,portions,targets,tolerance,macro_tolerance)
    if issues:lines+=['ВНИМАНИЕ: результат после подбора/ручных правок:',*issues,'']
    all_items=[]
    for day_index,day in enumerate(week,1):
        lines.append(f'ДЕНЬ {day_index}')
        for meal,recipe in zip(MEALS,day):
            values,estimated=recipe_nutrition(recipe)
            values={key:value*portions if value is not None else None for key,value in values.items()}
            info=servings_info(recipe)
            lines += [f'{meal}: {recipe.name} · {people*portions:g} порций на семью',
                      'Теги: '+', '.join(recipe_tags(recipe)),
                      ('≈ ' if estimated else '')+nutrition_text(values),
                      info.explanation,products_text([(recipe,people*portions)])]
            if recipe.source_url:lines.append('Источник (фото/видео): '+recipe.source_url)
            lines.append('')
        lines+=['КБЖУ за день на человека: '+nutrition_text(nutrition_totals([(r,portions) for r in day])),
                'ПРОДУКТЫ ЗА ДЕНЬ:',products_text([(r,people*portions) for r in day]),'']
        all_items.extend((r,people*portions) for r in day)
    family=nutrition_totals(all_items)
    lines+=['ИТОГО ЗА НЕДЕЛЮ','КБЖУ на человека: '+nutrition_text({k:v/people if v is not None else None for k,v in family.items()}),
            'Среднее за день на человека: '+nutrition_text({k:v/people/7 if v is not None else None for k,v in family.items()}),
            '\nСПИСОК ПОКУПОК НА НЕДЕЛЮ',products_text(all_items)]
    if any(v is None for v in family.values()):
        known=dict.fromkeys(KEYS,0.)
        for recipe,count in all_items:
            values,_=recipe_nutrition(recipe)
            for k,v in values.items():
                if v is not None:known[k]+=v*count
        lines+=['\nКБЖУ только известной части недели на человека (НЕ полный итог): '+nutrition_text({k:v/people for k,v in known.items()})]
    return '\n'.join(lines)


def day_recipe_text(recipe,people,portions):
    values,estimated=recipe_nutrition(recipe)
    per_person={k:v*portions if v is not None else None for k,v in values.items()}
    info=servings_info(recipe)
    lines=[recipe.name,'Теги: '+', '.join(recipe_tags(recipe)),
           'КБЖУ на человека за этот приём пищи: '+('≈ ' if estimated else '')+nutrition_text(per_person),
           f'Готовим {people*portions:g} порций на {people} человек.',info.explanation,
           '\nПРОДУКТЫ НА ВСЮ СЕМЬЮ:',products_text([(recipe,people*portions)]),
           '\nПРИГОТОВЛЕНИЕ:',recipe.method or 'Способ приготовления пока не заполнен.']
    if recipe.source_url:lines+=['\nИСТОЧНИК · фото и видео:',recipe.source_url]
    return '\n'.join(lines)
