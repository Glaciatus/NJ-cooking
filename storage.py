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
