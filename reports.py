from core import MEALS, totals
from nutrition import KEYS, recipe_nutrition, nutrition_totals, nutrition_text, ingredient_amount
from estimation import servings_info
from tagging import recipe_tags
from weekly_balance import daily_bounds


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


def balance_options(context):
    return {key:context.get(key,default) for key,default in (
        ('nutrition_mode','daily'),('daily_kcal_spread',.3),('daily_macro_spread',.5),('protein_floor',.75))}


def week_issues(week, portions, targets, tolerance, macro_tolerance,nutrition_mode='daily',daily_kcal_spread=.3,daily_macro_spread=.5,protein_floor=.75):
    issues=[]
    labels={'kcal':('Калории','ккал'),'protein':('Белки','г'),'fat':('Жиры','г'),'carbs':('Углеводы','г')}
    guard=daily_bounds(targets,daily_kcal_spread,daily_macro_spread,protein_floor)
    daily=[nutrition_totals([(r,portions) for r in day]) for day in week]
    def check(values,prefix,limits):
        for k in KEYS:
            if values[k] is None:continue
            low,high=limits[k]
            if values[k]<low-1e-8 or values[k]>high+1e-8:
                label,unit=labels[k]
                difference=low-values[k] if values[k]<low else values[k]-high
                direction='ниже минимума' if values[k]<low else 'выше максимума'
                issues.append(f'{prefix}: {label} — {values[k]:.2f} {unit}; допустимо {low:.2f}–{high:.2f} {unit}; {direction} на {difference:.2f} {unit}.')
    usual={k:(max(0,targets[k]-(tolerance if k=='kcal' else targets[k]*macro_tolerance)),targets[k]+(tolerance if k=='kcal' else targets[k]*macro_tolerance)) for k in KEYS}
    for n,values in enumerate(daily,1):
        if any(v is None for v in values.values()):issues.append(f'День {n}: КБЖУ известно частично.')
        check(values,f'День {n}',guard if nutrition_mode=='weekly' else usual)
    if nutrition_mode=='weekly' and daily:
        average={k:sum(d[k] for d in daily)/len(daily) if all(d[k] is not None for d in daily) else None for k in KEYS}
        check(average,'Среднее за день недели',usual)
        if any(v is None for v in average.values()):issues.append('Среднее КБЖУ за неделю известно частично; недельный баланс не подтверждён.')
    return issues


def week_report(week, people, portions, targets, tolerance, macro_tolerance, require_nutrition=True,extra_warnings=(),nutrition_mode="daily",daily_kcal_spread=.3,daily_macro_spread=.5,protein_floor=.75):
    lines=['МЕНЮ НА НЕДЕЛЮ',f'Человек: {people}; порций на человека за приём пищи: {portions:g}',
           'Цель на человека в сутки: '+nutrition_text(targets),
           f'Допуски: ±{tolerance:g} ккал; БЖУ ±{macro_tolerance*100:g}%.',
           'Контроль КБЖУ: '+('заданы строгие пределы; фактические отклонения перечислены ниже' if require_nutrition else 'выключен; цели используются только как пожелание'),
           'Разные строки продуктов складываются: граммы + стаканы + ложки; это не варианты замены.\nКБЖУ ниже — на человека, продукты — на всю семью. «≈» — оценка по USDA/справочнику, средним массам и выходу. Неизвестно не означает ноль.\n']
    options=dict(nutrition_mode=nutrition_mode,daily_kcal_spread=daily_kcal_spread,daily_macro_spread=daily_macro_spread,protein_floor=protein_floor)
    lines.insert(3,'Режим КБЖУ: '+('недельный баланс — цели и допуски относятся к среднему за день недели' if nutrition_mode=='weekly' else 'строгий дневной — цели и допуски на каждый день'))
    if nutrition_mode=='weekly':
        guard=daily_bounds(targets,daily_kcal_spread,daily_macro_spread,protein_floor)
        lines.insert(4,'Дневные границы на человека: '+ '; '.join(f'{label} {guard[k][0]:.2f}–{guard[k][1]:.2f} {unit}' for k,label,unit in [('kcal','Калории','ккал'),('protein','Белки','г'),('fat','Жиры','г'),('carbs','Углеводы','г')]))
    issues=week_issues(week,portions,targets,tolerance,macro_tolerance,**options)+list(extra_warnings)
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
    if recipe.source_nutrition_per100g:lines+=['\nКБЖУ САЙТА НА 100 Г (не на порцию): '+nutrition_text(recipe.source_nutrition_per100g)]
    if recipe.image_url:lines+=['\nФОТО:',recipe.image_url]
    if recipe.video_url:lines+=['\nВИДЕО:',recipe.video_url]
    if recipe.source_url:lines+=['\nИСТОЧНИК · фото и видео:',recipe.source_url]
    return '\n'.join(lines)
