"""Create bundled recipes from the supplied russian-recipes-parser archive.
Uses the already converted compatibility ZIP plus original category/tag metadata.
Usage: python tools/build_bundle.py original.zip converted.zip
"""
from pathlib import Path
import sys,zipfile,json,gzip,re,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Recipe,Ingredient
from tagging import infer_tags
from nutrition import normalize

def main(original,converted):
    with zipfile.ZipFile(original) as z:
        originals={}
        for name in z.namelist():
            if '/storage/recipes/' in name and name.endswith('.json'):
                row=json.loads(z.read(name));originals[row.get('source')]=row
    with zipfile.ZipFile(converted) as z:rows=json.loads(z.read('recipes.json'))
    estimates=0
    for data in rows:
        source=originals.get(data['source_url'],{})
        data['uid']=uuid.uuid5(uuid.NAMESPACE_URL,data['source_url']).hex
        data['source_category']=source.get('category') or ''
        data['reviewed']=True
        data['import_notes']=['Встроенная база vkuso.ru. КБЖУ рассчитывается по USDA/справочнику; неизвестные значения не заменяются нулями.']
        data['tags']=infer_tags(data['name'],data['source_category'],[t['name'] for t in source.get('tags',[])],
                                [Ingredient(**i) for i in data['ingredients']])
        flat=[i for g in source.get('ingredients',[]) for i in g.get('list',[])]
        for i,raw in zip(data['ingredients'],flat):
            if i['amount'] is not None:continue
            value=str(raw.get('value') or '').replace(',','.').strip()
            match=re.fullmatch(r'(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)',value)
            if match:
                lo,hi=map(float,match.groups())
                if 0<lo<=hi:
                    i['amount_estimate']=(lo+hi)/2
                    i['amount_basis']='Середина исходного диапазона '+value
                    estimates+=1
            if raw.get('amount')=='по вкусу' and normalize(i['name']) in ('соль','перец черный молотый','специи','корица','ванилин','перец черный горошком','лавровый лист'):
                i['amount_estimate']=1 if normalize(i['name'])=='соль' else .2
                i['unit']='г'
                i['amount_basis']='Условное количество «по вкусу», г; исправьте при необходимости.'
                estimates+=1
        # Category memberships do not force desserts into lunch; this field remains editable.
        if any(t in data['tags'] for t in ('Десерт','Выпечка','Каша')) and not any(t in data['tags'] for t in ('Мясное блюдо','Птица','Рыба и морепродукты','Суп')):
            data['meal']='Завтрак'
        elif 'Суп' in data['tags']:data['meal']='Обед'
    target=Path(__file__).resolve().parents[1]/'data'/'recipes.json.gz'
    with gzip.open(target,'wt',encoding='utf-8') as f:json.dump(rows,f,ensure_ascii=False,separators=(',',':'))
    print('Bundled recipes:',len(rows),'explicit quantity estimates:',estimates,'compressed bytes:',target.stat().st_size)

if __name__=='__main__':main(*sys.argv[1:])
