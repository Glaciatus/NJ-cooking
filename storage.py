"""Atomic, backwards-compatible local storage with last-version backup."""
import json
from pathlib import Path
import shutil
import tempfile
from core import Recipe


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + '.bak'))
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_recipes(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        content = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(content, list):
            raise ValueError('ожидался список рецептов')
        return [Recipe.from_dict(item) for item in content]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f'Не удалось прочитать {path}. Данные не перезаписаны. Резервная копия: {path.name}.bak. Причина: {exc}') from exc


def save_recipes(path, recipes):
    save_json(path, [r.to_dict() for r in recipes])


from functools import lru_cache
import copy
import gzip
import uuid

@lru_cache(maxsize=1)
def bundled_recipes():
    with gzip.open(Path(__file__).resolve().parent/'data'/'recipes.json.gz','rt',encoding='utf-8') as handle:
        return [Recipe.from_dict(row) for row in json.load(handle)]


def load_library(path, include_bundled=True):
    """Old array files migrate to overlays on next save; user fields take priority."""
    path=Path(path)
    if not include_bundled:return load_recipes(path)
    base=copy.deepcopy(bundled_recipes())
    hidden=set()
    legacy_format=True
    user=[]
    if path.exists():
        try:
            content=json.loads(path.read_text(encoding='utf-8'))
            if isinstance(content,list):user=[Recipe.from_dict(r) for r in content]
            elif isinstance(content,dict) and content.get('format')==2:
                legacy_format=False
                user=[Recipe.from_dict(r) for r in content['overrides']]
                hidden=set(content['hidden_ids'])
            else:raise ValueError('неизвестный формат')
        except (OSError,ValueError,TypeError,KeyError) as exc:
            raise ValueError(f'Библиотека {path} не прочитана, данные не перезаписаны: {exc}') from exc
    by_source={r.source_url:r for r in base}
    seen_ids=set()
    for n,r in enumerate(user):
        if r.uid in seen_ids:r.uid=uuid.uuid5(uuid.NAMESPACE_URL,r.uid+':variant:'+str(n)+':'+r.name).hex
        seen_ids.add(r.uid)
    claimed={r.source_url for r in user if r.source_url in by_source and r.uid==by_source[r.source_url].uid}
    for r in user:
        built=by_source.get(r.source_url)
        if built and built.uid not in hidden and (r.uid==built.uid or legacy_format and r.source_url not in claimed):
            claimed.add(r.source_url)
            legacy_stock=not r.reviewed and bool(r.import_notes) and r.import_notes[0].startswith('Импорт пользовательской базы vkuso.ru')
            if legacy_stock and r.meal=='Любой':r.meal=built.meal
            r.reviewed=True  # legacy approval flag is no longer a gate
            r.uid=built.uid
            if r.tags is None:r.tags=list(built.tags)
            if not r.source_category:r.source_category=built.source_category
            if r.import_notes and r.import_notes[0].startswith('Импорт пользовательской базы vkuso.ru'):
                r.import_notes=list(built.import_notes)
            for item,b in zip(r.ingredients,built.ingredients):
                if item.name==b.name and item.amount is None and item.original==b.original:
                    item.amount_estimate=b.amount_estimate
                    item.amount_basis=b.amount_basis
                    if not item.unit:item.unit=b.unit
    overrides={r.uid:r for r in user}
    result=[overrides.pop(r.uid,r) for r in base if r.uid not in hidden]
    result.extend(overrides.values())
    return result


def save_library(path, recipes, include_bundled=True):
    if not include_bundled:
        save_recipes(path,recipes)
        return
    base={r.uid:r for r in bundled_recipes()}
    present={r.uid for r in recipes}
    overrides=[r.to_dict() for r in recipes if r.uid not in base or r!=base[r.uid]]
    save_json(path,{'format':2,'overrides':overrides,'hidden_ids':sorted(base.keys()-present)})
