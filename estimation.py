"""Transparent category/weight heuristics. No hidden two-serving fallback."""
from dataclasses import dataclass
from nutrition import ingredient_mass, ingredient_amount, normalize
from tagging import recipe_tags

@dataclass(frozen=True)
class ServingsInfo:
    servings: float | None
    estimated: bool
    output_g: float | None
    explanation: str

# Prepared edible weight per person. These are editable planning assumptions, not nutrition norms.
PORTION_GRAMS={'Суп':350,'Гарнир':180,'Каша':250,'Салат':200,'Мясное блюдо':300,
               'Птица':300,'Рыба и морепродукты':300,'Овощное блюдо':250,
               'Десерт':140,'Выпечка':120,'Закуска':120,'Соус':30,'Напиток':250}

def servings_info(recipe):
    if recipe.servings:
        return ServingsInfo(recipe.servings,False,None,'Число порций указано в рецепте/вручную.')
    tags=recipe_tags(recipe)
    if 'Заготовка' in tags:
        return ServingsInfo(None,True,None,'Для заготовки укажите число порций вручную.')
    category=next((t for t in PORTION_GRAMS if t in tags),None)
    if category is None:
        return ServingsInfo(None,True,None,'Не определена категория для оценки выхода.')
    known=[];unknown=[];omitted=[]
    for i in recipe.ingredients:
        mass=ingredient_mass(i)
        if mass is None:
            if normalize(i.name) in ('соль','перец черный молотый','перец черный горошком','специи','ванилин','лавровый лист','корица','корица молотая','приправы'):
                omitted.append(i.name)
            else:unknown.append(i.name)
        else:known.append((i,mass))
    if not known or unknown:
        return ServingsInfo(None,True,None,'Для оценки выхода не хватает массы: '+', '.join(unknown[:4])+'.')
    total=sum(m for _,m in known)
    water_present=any(normalize(i.name) in ('вода','water','бульон','бульон куриный','бульон овощной') for i,_ in known)
    adjusted=0
    for i,mass in known:
        name=normalize(i.name)
        factor=1
        if category not in ('Десерт','Выпечка','Соус','Закуска'):
            if any(w in name for w in ('рис','греч','макарон','чечевиц','овсян','овсяные','перлов')) and not any(w in name for w in ('варен','готов','мука','рисов','масло')):
                # Water explicitly included in the recipe already contributes to total mass.
                factor=1 if water_present else (2.5 if 'макарон' in name else 2.8)
            elif any(w in name for w in ('говядин','свинин','курин','филе','фарш','лосось','индейк')):
                factor=.75
        adjusted+=mass*factor
    if category in ('Выпечка','Десерт'):
        # No blanket baking loss for cold puddings/ice cream.
        if any(w in recipe.name.casefold() for w in ('печенье','пирог','кекс','хлеб','бисквит','булоч')):
            adjusted*=.9
    if adjusted<=0:return ServingsInfo(None,True,None,'Нулевая оценка выхода; уточните состав.')
    servings=max(1,int(adjusted/PORTION_GRAMS[category]+.5))
    text=f'≈ {servings} порц.: выход ≈ {adjusted:.0f} г / {PORTION_GRAMS[category]} г; категория «{category}». Средние массы и коэффициенты готовки.'
    if omitted:text+=' Неизвестные малые количества приправ не включены в вес: '+', '.join(omitted)+'.'
    return ServingsInfo(servings,True,adjusted,text)
