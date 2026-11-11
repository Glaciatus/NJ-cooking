"""Offline official USDA records and explicit Russian aliases; no fuzzy auto-match."""
from functools import lru_cache
from pathlib import Path
import gzip,json

DATA_DIR=Path(__file__).resolve().parent/'data'

@lru_cache(maxsize=1)
def records():
    with gzip.open(DATA_DIR/'usda.json.gz','rt',encoding='utf-8') as f:
        return {row['id']:row for row in json.load(f)}

@lru_cache(maxsize=1)
def aliases():
    return json.loads((DATA_DIR/'ru_usda_aliases.json').read_text(encoding='utf-8'))


def search_foods(query, limit=100):
    words=query.casefold().split()
    if not words:return []
    if len(words)==1 and words[0].isdigit():
        row=records().get(int(words[0]));return [row] if row else []
    names={v['fdc_id'] for k,v in aliases().items() if all(w in k for w in words)}
    return [r for r in records().values() if r['id'] in names or all(w in r['description'].casefold() for w in words)][:limit]
