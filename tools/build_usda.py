"""Reduce official uploaded USDA JSON archives to offline nutrient/portion records.
Usage: python tools/build_usda.py output.json.gz archive1.zip archive2.zip
"""
import gzip,json,sys,zipfile
from pathlib import Path

def build(paths):
    records=[]
    for path in paths:
        with zipfile.ZipFile(path) as z:
            name=next(n for n in z.namelist() if n.endswith('.json'))
            dataset=json.loads(z.read(name))
        for rows in dataset.values():
            for row in rows:
                nutrients={n['nutrient']['id']:n.get('amount') for n in row.get('foodNutrients',[]) if n.get('amount') is not None}
                energy=next((nutrients[k] for k in (1008,2048,2047) if k in nutrients),None)
                if energy is None and 1062 in nutrients:energy=nutrients[1062]/4.184
                values=[energy,nutrients.get(1003),nutrients.get(1004),nutrients.get(1005)]
                if not any(v is not None for v in values):continue
                measures=[]
                for p in row.get('foodPortions',[]):
                    if p.get('gramWeight') and p.get('amount'):
                        unit=p.get('measureUnit',{}).get('name','')
                        label=' '.join(s for s in (unit if unit!='undetermined' else '',p.get('modifier',''),p.get('portionDescription','')) if s)
                        measures.append({'label':label,'grams':p['gramWeight']/p['amount']})
                records.append({'id':row['fdcId'],'description':row['description'],'dataset':row['dataType'],'values':values,'measures':measures})
        del dataset
    return records

if __name__=='__main__':
    records=build(sys.argv[2:])
    with gzip.open(sys.argv[1],'wt',encoding='utf-8') as f:json.dump(records,f,ensure_ascii=False,separators=(',',':'))
    print('USDA nutrient records:',len(records))
