"""Import public recipe pages with schema.org Recipe JSON-LD. Never executes page code."""
from html import unescape
from html.parser import HTMLParser
from fractions import Fraction
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from core import Recipe, Ingredient, validate_recipe
from diagnostics import APP_VERSION

MAX_PAGE = 4_000_000

class ImportFailure(ValueError):
    pass


def public_url(url):
    url = url.strip()
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        host = parsed.hostname.casefold()
        if host == 'localhost' or host.endswith(('.local', '.localhost')):
            raise ValueError
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError
        except ValueError as e:
            # A non-IP hostname is fine; a parsed but private IP is not.
            if re.fullmatch(r'[\d.]+', host) or ':' in host:
                raise ValueError from e
        if parsed.port not in (None, 80, 443):
            raise ValueError
    except ValueError:
        raise ImportFailure('Вставьте публичную ссылку http:// или https:// без логина и пароля.') from None
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def decode_html(raw,header_encoding=None):
    if raw.startswith(b'\xef\xbb\xbf'):return raw.decode('utf-8-sig')
    declared=re.search(rb'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)',raw[:8192],re.I)
    choices=[header_encoding,declared[1].decode('ascii') if declared else None,'utf-8','windows-1251']
    for encoding in choices:
        if not encoding:continue
        try:return raw.decode(encoding)
        except (UnicodeDecodeError,LookupError):pass
    return raw.decode('utf-8',errors='replace')


def fetch_page(url):
    url = public_url(url)
    request = urllib.request.Request(url, headers={
        'User-Agent': f'NJ-Cooking/{APP_VERSION} (personal recipe importer)',
        'Accept': 'text/html,application/xhtml+xml', 'Accept-Encoding': 'identity'})
    try:
        with urllib.request.build_opener(SafeRedirect()).open(request, timeout=15) as response:
            final_url = public_url(response.geturl())
            if response.headers.get_content_type() not in ('text/html', 'application/xhtml+xml'):
                raise ImportFailure('Ссылка ведёт не на HTML-страницу рецепта.')
            content = response.read(MAX_PAGE + 1)
            if len(content) > MAX_PAGE:
                raise ImportFailure('Страница слишком большая (более 4 МБ).')
            text=decode_html(content,response.headers.get_content_charset())
            return text, final_url
    except urllib.error.HTTPError as e:
        raise ImportFailure(f'Сайт вернул HTTP {e.code}. Возможно, он запрещает автоматический импорт. Ссылку можно сохранить вручную.') from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        if 'Tunnel connection failed: 403' in str(getattr(e, 'reason', '')):
            raise ImportFailure('Сетевой прокси запретил доступ к сайту (403). Разрешите домен в настройках сети среды или импортируйте рецепт на своём ПК.') from e
        raise ImportFailure('Не удалось загрузить страницу. Проверьте интернет и ссылку; сайт может ограничивать доступ.') from e


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'script':
            attributes = dict(attrs)
            if attributes.get('type', '').lower().split(';')[0].strip() == 'application/ld+json':
                self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self.current is not None:
            self.blocks.append(''.join(self.current))
            self.current = None


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
    def handle_data(self, data):
        self.text.append(data)


def clean(value):
    if not isinstance(value, str):
        return ''
    parser = TextParser()
    parser.feed(value)
    return ' '.join(unescape(' '.join(parser.text)).split())


def find_recipes(node):
    if isinstance(node, list):
        for item in node:
            yield from find_recipes(item)
    elif isinstance(node, dict):
        types = node.get('@type', [])
        if isinstance(types, str):
            types = [types]
        if any(str(t).rstrip('/').split('/')[-1] == 'Recipe' for t in types):
            yield node
        else:
            for value in node.values():
                if isinstance(value, (list, dict)):
                    yield from find_recipes(value)


def quantity(text):
    text = text.strip().replace(',', '.')
    for char, replacement in {'½': ' 1/2', '¼': ' 1/4', '¾': ' 3/4', '⅓': ' 1/3', '⅔': ' 2/3', '⅛': ' 1/8'}.items():
        text = text.replace(char, replacement)
    return sum(float(Fraction(part)) for part in text.split())

UNIT_ALIASES = {
    'г': 'г', 'гр': 'г', 'грамм': 'г', 'грамма': 'г', 'граммов': 'г', 'g': 'г', 'grams': 'г', 'gram': 'г',
    'кг': 'кг', 'kg': 'кг', 'мл': 'мл', 'ml': 'мл', 'л': 'л', 'l': 'л',
    'шт': 'шт', 'штука': 'шт', 'штуки': 'шт', 'штук': 'шт', 'pcs': 'шт',
    'ст. ложка': 'ст. л.', 'ст. ложки': 'ст. л.', 'ч. ложка': 'ч. л.', 'ч. ложки': 'ч. л.',
    'щепотка': 'щепотка', 'щепотки': 'щепотка', 'зубчик': 'зубчик', 'зубчика': 'зубчик',
    'cup': 'cup', 'cups': 'cup', 'tbsp': 'ст. л.', 'tsp': 'ч. л.', 'ст. л.': 'ст. л.', 'ч. л.': 'ч. л.',
    'oz': 'oz', 'lb': 'lb', 'lbs': 'lb', 'teaspoon': 'ч. л.', 'tablespoon': 'ст. л.',
}
UNITS = '|'.join(re.escape(k) for k in sorted(UNIT_ALIASES, key=len, reverse=True))
QTY = r'(?:\d+(?:[.,]\d+)?(?:\s+\d+/\d+|/\d+|[½¼¾⅓⅔⅛])?|[½¼¾⅓⅔⅛])'


def parse_ingredient(raw):
    raw = clean(raw)
    original=raw
    # Prefer an explicit mass over an estimated piece/clove weight.
    weight=re.search(r'\((\d+(?:[.,]\d+)?)\s*(г|кг|мл|л)\)\s*$',raw,re.I)
    split=re.split(r'\s+[—–-]\s+|:\s+',raw,maxsplit=1)
    if weight and len(split)==2:
        amount=float(weight[1].replace(',','.'))
        if amount>0:return Ingredient(split[0],amount,weight[2].casefold(),original=original)
    # Discard only trailing annotations after a quantity, preserving e.g. «фарш (свиной)».
    if re.search(r'\d\s*(?:г|мл|кг|шт\.?)\s+\([^)]*\)\s*$',raw,re.I):raw=re.sub(r'\s*\([^)]*\)\s*$','',raw)
    # Our paste format is also supported; ordinary website lines need no semicolons.
    if raw.count(';') == 2:
        name, amount, unit = (p.strip() for p in raw.split(';'))
        try:
            value = quantity(amount)
            if value > 0:
                return Ingredient(name, value, UNIT_ALIASES.get(unit.casefold(), unit), original=original)
        except (ValueError, ZeroDivisionError):
            pass
    patterns = [rf'^(?P<q>{QTY})\s*(?P<u>{UNITS})\.?\s+(?P<n>.+)$',
                rf'^(?P<n>.+?)\s*[—–:-]?\s+(?P<q>{QTY})\s*(?P<u>{UNITS})\.?$']
    for pattern in patterns:
        match = re.match(pattern, raw, flags=re.I)
        if match:
            try:
                value = quantity(match['q'])
                raw_name = match['n']
                name = raw_name.strip(' —–-:')
                # A range must not become a single guessed quantity.
                if not re.search(r'\d\s*[-–—]\s*$', raw_name) and value > 0:
                    return Ingredient(name, value, UNIT_ALIASES[match['u'].casefold()], original=original)
            except (ValueError, ZeroDivisionError):
                pass
    unknown_name=re.split(r'\s+[—–-]\s+|:\s+',original,maxsplit=1)[0]
    return Ingredient(unknown_name or 'Неизвестный продукт',None,'',original=original)


def steps(value):
    if isinstance(value, str):
        return [clean(value)]
    if isinstance(value, list):
        return [line for item in value for line in steps(item)]
    if isinstance(value, dict):
        if value.get('itemListElement'):
            return steps(value['itemListElement'])
        return steps(value.get('text', ''))
    return []


def schema_number(value, *, energy=False):
    if isinstance(value, dict):
        value = value.get('value')
    match = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*([\w ]*)\s*', str(value or ''))
    if not match:
        return None
    amount = float(match[1].replace(',', '.'))
    unit = match[2].strip().casefold()
    if energy:
        if unit in ('kj', 'килоджоулей', 'кдж'):
            amount /= 4.184
        elif unit not in ('', 'kcal', 'cal', 'calories', 'ккал'):
            return None
    elif unit in ('mg', 'мг'):
        amount /= 1000
    elif unit not in ('', 'g', 'г', 'grams'):
        return None
    return amount


def from_schema(data, url):
    notes = ['Проверьте распознавание продуктов, порций и КБЖУ перед сохранением.']
    yield_value = data.get('recipeYield', '')
    if isinstance(yield_value, list):
        yield_value = yield_value[0] if yield_value else ''
    # Do not confuse "12 cookies" or "1 loaf" with number of servings.
    match = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*(?:servings?|порци[яийю]|persons?|people)?\s*', str(yield_value), re.I)
    servings = float(match[1].replace(',', '.')) if match else None
    if not servings or servings <= 0:
        servings = None
        notes.append(f'Уточните порции. На сайте: {yield_value or "не указано"}.')
    raw_ingredients = data.get('recipeIngredient', [])
    if isinstance(raw_ingredients, str):
        raw_ingredients = raw_ingredients.splitlines()
    ingredients = [parse_ingredient(i) for i in raw_ingredients if isinstance(i, str) and i.strip()] if isinstance(raw_ingredients, list) else []
    raw_nutrition = data.get('nutrition') or {}
    source_per100g=None
    values = dict.fromkeys(('kcal', 'protein', 'fat', 'carbs'))
    if isinstance(raw_nutrition, dict):
        basis = str(raw_nutrition.get('servingSize', '')).strip()
        # A mass-based servingSize is ambiguous relative to recipeYield.
        if basis and not re.fullmatch(r'1\s*(?:serving|portion|порция)', basis, re.I):
            if re.fullmatch(r'100\s*(?:g|г|гр\.?)',basis,re.I):
                source_per100g={key:schema_number(raw_nutrition.get(field),energy=key=='kcal') for key,field in (('kcal','calories'),('protein','proteinContent'),('fat','fatContent'),('carbs','carbohydrateContent'))}
            notes.append(f'КБЖУ сайта относится к «{basis}». Сохранено отдельно, не как КБЖУ на порцию.')
        else:
            for key, source in (('kcal', 'calories'), ('protein', 'proteinContent'), ('fat', 'fatContent'), ('carbs', 'carbohydrateContent')):
                values[key] = schema_number(raw_nutrition.get(source), energy=key == 'kcal')
            if any(v is not None for v in values.values()):
                notes.append('КБЖУ сайта перенесено как значения на одну порцию (schema.org). Проверьте на странице.')
    if any(i.amount is None for i in ingredients):
        notes.append('У некоторых продуктов не распознаны количества. Они помечены «уточнить».')
    from site_importers import media_url
    image=data.get('image') or ''
    if isinstance(image,list):image=image[0] if image else ''
    if isinstance(image,dict):image=image.get('url') or image.get('contentUrl') or ''
    video=data.get('video') or ''
    if isinstance(video,list):video=video[0] if video else ''
    if isinstance(video,dict):video=video.get('contentUrl') or video.get('embedUrl') or video.get('url') or ''
    category=data.get('recipeCategory') or ''
    if isinstance(category,list):category=', '.join(str(x) for x in category)
    recipe = Recipe(clean(data.get('name', '')) or 'Импортированный рецепт', servings, ingredients=ingredients,
                    method='\n'.join(steps(data.get('recipeInstructions', ''))), source_url=url,
                    import_notes=notes,reviewed=False,source_category=clean(category),image_url=media_url(image,url),video_url=media_url(video,url),source_nutrition_per100g=source_per100g,**values)
    validate_recipe(recipe)
    return recipe


def parse_page(html, url):
    public_url(url)
    parser = PageParser()
    parser.feed(html)
    recipes = []
    seen = set()
    for block in parser.blocks:
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for item in find_recipes(data):
            recipe = from_schema(item, url)
            signature = (recipe.name, tuple(i.original for i in recipe.ingredients))
            if signature not in seen:
                recipes.append(recipe)
                seen.add(signature)
    if not recipes:
        from site_importers import extract_html_recipes
        extracted,backend=extract_html_recipes(html,url)
        for data in extracted:
            recipe=from_schema(data,url)
            recipe.import_notes.insert(0,'Импорт: '+backend+'.')
            recipes.append(recipe)
    if not recipes:
        raise ImportFailure('На странице не найден рецепт Recipe (JSON-LD/microdata) или поддерживаемый HTML RussianFood. Возможна блокировка сайта или изменение разметки. Сохраните HTML страницы для проверки.')
    return recipes


def import_url(url):
    html, final_url = fetch_page(url)
    return parse_page(html, final_url)


def import_docx(path):
    """Split explicit Word headings, or a title immediately preceding a portions line.

    Only labelled ingredient/method sections are interpreted; ambiguous content
    remains in the preparation field for review, rather than silently disappearing.
    """
    import zipfile
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as document:
        if document.getinfo('word/document.xml').file_size > 10_000_000:
            raise ImportFailure('Документ слишком большой (максимум 10 МБ текста).')
        root = ET.fromstring(document.read('word/document.xml'))
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    paragraphs = []
    for paragraph in root.findall('.//w:p', ns):
        text = ''.join(t.text or '' for t in paragraph.findall('.//w:t', ns)).strip()
        style = paragraph.find('./w:pPr/w:pStyle', ns)
        style_name = style.get('{'+ns['w']+'}val', '') if style is not None else ''
        if text:
            paragraphs.append((text, style_name))
    if not paragraphs:
        raise ImportFailure('В документе не найден текст рецептов.')
    section = re.compile(r'^(ингредиенты|продукты|состав|приготовление|способ приготовления|инструкция)\s*[:.]?$', re.I)
    serving = re.compile(r'(?:количество\s+)?порци[йия]\s*[:—-]?\s*(\d+(?:[.,]\d+)?)', re.I)
    explicit = {n for n, (text, style) in enumerate(paragraphs)
                if re.fullmatch(r'(?:heading[12]|заголовок[12]|title)', style, re.I) and not section.match(text)}
    starts = {0} | explicit
    if not explicit:
        for n, (text, _) in enumerate(paragraphs):
            if n > 0 and (serving.match(text) or section.match(text) and text.casefold().rstrip(':.') in ('ингредиенты', 'продукты', 'состав')):
                previous = paragraphs[n-1][0]
                if not section.match(previous) and not serving.search(previous) and len(previous) < 150 and parse_ingredient(previous).amount is None:
                    starts.add(n-1)
    boundaries = sorted(starts) + [len(paragraphs)]
    recipes = []
    for begin, end in zip(boundaries, boundaries[1:]):
        lines = [text for text, _ in paragraphs[begin:end]]
        name = re.sub(r'^название\s*(?:рецепта)?\s*:\s*', '', lines[0], flags=re.I)
        servings, ingredients, method, extra, source = None, [], [], [], ''
        state = None
        for line in lines[1:]:
            match = serving.search(line)
            if match:
                servings = float(match[1].replace(',', '.')) or None
                continue
            label = re.match(r'^(ингредиенты|продукты|состав|приготовление|способ приготовления|инструкция)\s*[:.]?\s*(.*)$', line, re.I)
            if label:
                state = 'ingredients' if label[1].casefold() in ('ингредиенты', 'продукты', 'состав') else 'method'
                line = label[2].strip()
                if not line:
                    continue
            if state == 'ingredients':
                ingredients.append(parse_ingredient(line.lstrip('•*- ')))
            elif state == 'method':
                method.append(line)
            else:
                extra.append(line)
            url_match = re.search(r'https?://[^\s]+', line)
            if url_match and not source:
                try:
                    source = public_url(url_match[0])
                except ImportFailure:
                    pass
        preparation = '\n'.join(method)
        if extra:
            preparation += '\n\nТекст для проверки:\n' + '\n'.join(extra)
        notes = ['Импорт Word: проверьте границы рецепта, продукты, порции и приготовление. КБЖУ будет оценено по составу либо вводится вручную.']
        if not ingredients:
            notes.append('Не найден раздел «Ингредиенты»/«Продукты»/«Состав». Перенесите продукты из текста кнопкой «Вставить список».')
        recipes.append(Recipe(name, servings, None, ingredients, preparation.strip(), source_url=source, reviewed=False, import_notes=notes))
    return recipes


def import_html(path,source_url=None):
    from pathlib import Path
    from site_importers import saved_source
    if Path(path).stat().st_size>MAX_PAGE:raise ImportFailure('HTML-файл слишком большой (более 4 МБ).')
    raw=Path(path).read_bytes()
    if len(raw)>MAX_PAGE:raise ImportFailure('HTML-файл слишком большой (более 4 МБ).')
    markup=decode_html(raw)
    source=source_url or saved_source(markup)
    if not source:raise ImportFailure('В HTML не найдена ссылка на источник. Укажите её при импорте.')
    return parse_page(markup,public_url(source))
