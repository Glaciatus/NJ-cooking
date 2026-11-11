"""Editable multi-label recipe taxonomy. Empty explicit tags stay empty."""
TAGS = ('Суп','Гарнир','Мясное блюдо','Птица','Рыба и морепродукты','Салат','Овощное блюдо',
        'Каша','Десерт','Выпечка','Закуска','Соус','Напиток','Заготовка','Другое')


def infer_tags(name, category='', source_tags=(), ingredients=()):
    text=' '.join((name,category,*source_tags)).casefold().replace('ё','е')
    title=(name+' '+category).casefold().replace('ё','е')
    products=' '.join(i.name for i in ingredients).casefold().replace('ё','е')
    result=set()
    rules={
        'Суп':('суп','борщ','щи ','окрошк','солянк','рассольник','уха '),
        'Гарнир':('гарнир','картофельное пюре','рис на пару'),
        'Салат':('салат','винегрет'),
        'Каша':('каша','каши','овсян'),
        'Десерт':('десерт','торт','печенье','пирожное','морожен','пудинг','конфет','крем-брюле','крамбл','чизкейк'),
        'Выпечка':('выпеч','пирог','пирож','булоч','кекс','маффин','печенье','хлеб','блин','олад','пицц','ватруш','рулет из теста'),
        'Соус':('соус','заправка для','майонез домашний'),
        'Напиток':('напит','коктейль','лимонад','компот','морс','смузи','чай '),
        'Заготовка':('заготов','на зиму','варенье','джем','конфитюр','маринован'),
        'Закуска':('закуск','бутерброд','канапе','паштет'),
        'Овощное блюдо':('овощное','овощные блюда','рагу из овощ','овощное рагу'),
    }
    for tag,words in rules.items():
        context=title if tag in ('Соус','Напиток','Заготовка','Гарнир') else text
        if any(word in context for word in words):result.add(tag)
    if 'Соус' in result and 'соус' not in category.casefold() and not name.casefold().startswith(('соус','заправка','домашний майонез')):
        result.discard('Соус')
    if 'без выпечки' in text:result.discard('Выпечка')
    # Composition-based membership, not incidental mentions like "без мяса" in tags.
    if any(w in products for w in ('говядин','свинин','баранин','мясной фарш','фарш мясной','ветчина','бекон')):result.add('Мясное блюдо')
    if any(w in products for w in ('куриц','курин','индейк','индюш','утка','утино','гуся')):result.add('Птица')
    if any(w in products for w in ('рыба','лосос','семга','треск','минтай','тунец','кревет','кальмар','сельд','форель','горбуш','скумбр')):result.add('Рыба и морепродукты')
    main_tags={'Суп','Салат','Десерт','Выпечка','Соус','Напиток','Заготовка','Каша','Закуска'}
    if not result.intersection(main_tags|{'Мясное блюдо','Птица','Рыба и морепродукты'}):
        if any(w in products for w in ('картофель','греч','рис','макарон','булгур','кускус','перлов','чечевиц','фасоль','горох')):
            result.add('Гарнир')
        vegetables=('морковь','капуста','кабач','баклаж','помидор','свекл','брокколи','перец сладкий','перец болгарский')
        if sum(any(w in i.name.casefold() for w in vegetables) for i in ingredients)>=2:
            result.add('Овощное блюдо')
    if not result:result.add('Другое')
    return [tag for tag in TAGS if tag in result]


def recipe_tags(recipe):
    return recipe.tags if recipe.tags is not None else infer_tags(recipe.name, recipe.source_category, ingredients=recipe.ingredients)
