from core import MEALS, totals
from nutrition import KEYS, recipe_nutrition, nutrition_totals, nutrition_text


def products_text(items):
    return '\n'.join(f'  {name}: {amount:.1f}'.rstrip('0').rstrip('.') + f' {unit}'
                     for (name, unit), amount in sorted(totals(items).items()))


def week_report(week, people, portions, targets, tolerance, macro_tolerance):
    lines = ['МЕНЮ НА НЕДЕЛЮ', f'Человек: {people}; порций на человека за приём пищи: {portions:g}',
             'Цель на человека в сутки: ' + nutrition_text(targets),
             f'Допуски: ±{tolerance:g} ккал; БЖУ ±{macro_tolerance*100:g}%.',
             'КБЖУ ниже — на человека, продукты — на всю семью. «≈» означает оценку по справочнику/формуле.\n']
    all_items = []
    for day_index, day in enumerate(week, 1):
        lines.append(f'ДЕНЬ {day_index}')
        for meal, recipe in zip(MEALS, day):
            values, estimated = recipe_nutrition(recipe)
            values = {key: value * portions for key, value in values.items()}
            lines += [f'{meal}: {recipe.name} · {people*portions:g} порций на семью',
                      ('≈ ' if estimated else '') + nutrition_text(values),
                      products_text([(recipe, people * portions)])]
            if recipe.source_url:
                lines.append('Источник (фото/видео): ' + recipe.source_url)
            lines.append('')
        daily_items = [(r, portions) for r in day]
        lines += ['КБЖУ за день на человека: ' + nutrition_text(nutrition_totals(daily_items)),
                  'КБЖУ за день на семью: ' + nutrition_text(nutrition_totals([(r, people*portions) for r in day])),
                  'ПРОДУКТЫ ЗА ДЕНЬ:', products_text([(r, people * portions) for r in day]), '']
        all_items.extend((r, people * portions) for r in day)
    family = nutrition_totals(all_items)
    lines += ['ИТОГО ЗА НЕДЕЛЮ', 'КБЖУ на семью: ' + nutrition_text(family),
              'КБЖУ на человека: ' + nutrition_text({k: v / people for k, v in family.items()}),
              'Среднее за день на человека: ' + nutrition_text({k: v / people / 7 for k, v in family.items()}),
              '\nСПИСОК ПОКУПОК НА НЕДЕЛЮ', products_text(all_items)]
    return '\n'.join(lines)
