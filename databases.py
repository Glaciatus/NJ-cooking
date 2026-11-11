"""Independent recipe files, persistent source switches, quotas and mandatory picks."""
from dataclasses import dataclass,field,replace
from pathlib import Path
import uuid
from core import Recipe,recipe_key
from storage import load_library,save_library,load_recipes,save_recipes,save_json,bundled_recipes
import json

@dataclass
class Database:
    uid:str
    name:str
    path:Path
    bundled:bool=False
    enabled:bool=True
    quota:int|None=None
    required:set=field(default_factory=set)
    recipes:list=field(default_factory=list)

class DatabaseManager:
    def __init__(self,legacy_path,include_bundled=True):
        self.legacy_path=Path(legacy_path)
        self.registry_path=self.legacy_path.with_name('databases.json')
        self.databases=[]
        if self.registry_path.exists():
            data=json.loads(self.registry_path.read_text(encoding='utf-8-sig'))
            if not isinstance(data,dict) or data.get('format')!=1:raise ValueError('Неизвестный формат списка баз данных.')
            for row in data['databases']:
                path=Path(row['path'])
                if not path.is_absolute():path=self.registry_path.parent/path
                self.databases.append(Database(row['uid'],row['name'],path,row.get('bundled',False),row.get('enabled',True),row.get('quota'),set(row.get('required',[]))))
        else:
            if include_bundled:
                library=load_library(self.legacy_path,True)  # Validate legacy data before writing anything.
                built_ids={r.uid for r in bundled_recipes()}
                big=self.legacy_path.with_name('bundled-overrides.json')
                personal=self.legacy_path.with_name('personal-recipes.json')
                if not big.exists():save_library(big,[r for r in library if r.uid in built_ids],True)
                if not personal.exists():save_recipes(personal,[r for r in library if r.uid not in built_ids])
                self.databases.append(Database('bundled','Большая база · 13 703',big,True))
            else:
                personal=self.legacy_path
                if not personal.exists():save_recipes(personal,[])
            self.databases.append(Database('personal','Личная база',personal))
            self.persist()
        if len({d.uid for d in self.databases})!=len(self.databases):raise ValueError('Повторные идентификаторы баз.')
        self.reload()

    def get(self,uid):
        return next(d for d in self.databases if d.uid==uid)

    def persist(self):
        rows=[]
        for d in self.databases:
            try:path=str(d.path.relative_to(self.registry_path.parent))
            except ValueError:path=str(d.path)
            rows.append({'uid':d.uid,'name':d.name,'path':path,'bundled':d.bundled,'enabled':d.enabled,'quota':d.quota,'required':sorted(d.required)})
        save_json(self.registry_path,{'format':1,'databases':rows})

    def reload(self):
        for d in self.databases:
            if not d.path.exists() and not d.enabled:
                d.recipes=[]
                continue
            if not d.path.exists():raise ValueError(f'База «{d.name}» не найдена: {d.path}')
            d.recipes=load_library(d.path,True) if d.bundled else load_recipes(d.path)
            if len({r.uid for r in d.recipes})!=len(d.recipes):raise ValueError(f'В базе «{d.name}» повторяются ID рецептов.')
            for r in d.recipes:r.database_id=d.uid

    def all_recipes(self):
        return [r for d in self.databases for r in d.recipes]

    def active_recipes(self):
        return [r for d in self.databases if d.enabled for r in d.recipes]

    def required_keys(self):
        return [recipe_key(r) for d in self.databases if d.enabled for r in d.recipes if r.uid in d.required]

    def limits(self):
        return {d.uid:d.quota for d in self.databases if d.enabled and d.quota is not None}

    def save_all(self,recipes):
        known={d.uid for d in self.databases}
        if any(r.database_id not in known for r in recipes):raise ValueError('Рецепт относится к неизвестной базе.')
        for d in self.databases:
            rows=[r for r in recipes if r.database_id==d.uid]
            if rows!=d.recipes:
                stored=[replace(r,database_id='') for r in rows]
                if d.bundled:save_library(d.path,stored,True)
                else:save_recipes(d.path,stored)
                d.recipes=rows
                d.required.intersection_update(r.uid for r in rows)
        self.persist()

    def connect(self,path,name=None):
        path=Path(path).resolve()
        if any(d.path.resolve()==path for d in self.databases):raise ValueError('Этот файл уже подключён.')
        if path.resolve() in {self.registry_path.resolve(),self.legacy_path.with_name('settings.json').resolve(),self.legacy_path.with_name('menu.json').resolve()}:
            raise ValueError('Это служебный файл, а не база рецептов.')
        rows=load_recipes(path)
        if not path.exists():raise ValueError('Выберите существующий файл базы.')
        if len({r.uid for r in rows})!=len(rows):raise ValueError('Повторные ID в базе рецептов.')
        d=Database(uuid.uuid4().hex,name or path.stem,path,recipes=rows)
        for r in rows:r.database_id=d.uid
        self.databases.append(d)
        try:self.persist()
        except Exception:
            self.databases.remove(d)
            raise
        return d

    def create(self,path,name=None):
        path=Path(path)
        if path.exists():raise ValueError('Файл уже существует. Используйте «Подключить» или выберите новое имя.')
        if any(d.path.resolve()==path.resolve() for d in self.databases):raise ValueError('Этот путь уже подключён.')
        if path.resolve() in {self.registry_path.resolve(),self.legacy_path.with_name('settings.json').resolve(),self.legacy_path.with_name('menu.json').resolve()}:
            raise ValueError('Это путь служебного файла; выберите другое имя базы.')
        save_recipes(path,[])
        return self.connect(path,name)

    def toggle_required(self,recipe):
        d=self.get(recipe.database_id)
        old=set(d.required)
        if recipe.uid in d.required:d.required.remove(recipe.uid)
        else:d.required.add(recipe.uid)
        try:self.persist()
        except Exception:
            d.required=old
            raise
        return recipe.uid in d.required
