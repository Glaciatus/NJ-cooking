"""Small inert HTML tree for microdata and RussianFood pages. Standard library only."""
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin
import re

class Node:
    def __init__(self,tag='',attrs=()):
        self.tag=tag;self.attrs=dict(attrs);self.children=[]
    def nodes(self):
        for child in self.children:
            if isinstance(child,Node):
                yield child;yield from child.nodes()
    def find(self,tag=None,prop=None,cls=None):
        return [n for n in self.nodes() if (tag is None or n.tag==tag) and (prop is None or prop in n.attrs.get('itemprop','').split()) and (cls is None or cls in n.attrs.get('class','').split())]
    def properties(self,prop):
        result=[]
        for child in self.children:
            if not isinstance(child,Node):continue
            if prop in child.attrs.get('itemprop','').split():result.append(child)
            if 'itemscope' not in child.attrs:result.extend(child.properties(prop))
        return result
    def text(self):
        def parts(node):
            if isinstance(node,str):yield node
            elif node.tag not in ('script','style','noscript'):
                for child in node.children:yield from parts(child)
        return ' '.join(' '.join(parts(self)).split())

class Document(HTMLParser):
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self,markup):
        super().__init__(convert_charrefs=True)
        self.root=Node();self.stack=[self.root];self.feed(markup)
    def handle_starttag(self,tag,attrs):
        # Optional closing tags used by older recipe tables/lists.
        boundaries={'li':('ul','ol'),'tr':('table',),'td':('tr',),'th':('tr',)}
        if tag in boundaries:
            boundary=max((i for i,n in enumerate(self.stack) if n.tag in boundaries[tag]),default=0)
            siblings=('td','th') if tag in ('td','th') else (tag,)
            previous=next((i for i in range(len(self.stack)-1,boundary,-1) if self.stack[i].tag in siblings),None)
            if previous is not None:del self.stack[previous:]
        node=Node(tag,attrs);self.stack[-1].children.append(node)
        if tag not in self.VOID:self.stack.append(node)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:
                del self.stack[i:];break
    def handle_data(self,data):self.stack[-1].children.append(data)


def value(node):
    return node.attrs.get('content') or node.attrs.get('datetime') or node.text()

def first(nodes):return value(nodes[0]) if nodes else ''

def media_url(raw,url):
    if not isinstance(raw,str) or not raw.strip():return ''
    raw=raw.strip()
    # Chrome replaces saved image sources with local resource folders; never invent a live URL for them.
    if '_files/' in raw or raw.startswith(('file:','data:','javascript:')):return ''
    absolute=urljoin(url,raw)
    return absolute if urlsplit(absolute).scheme in ('http','https') else ''


def meta(root,key):
    return next((n.attrs.get('content','') for n in root.find(tag='meta') if n.attrs.get('property')==key or n.attrs.get('name')==key),'')


def extract_microdata(root,url):
    scopes=[n for n in root.nodes() if any(t.rstrip('/').split('/')[-1]=='Recipe' for t in n.attrs.get('itemtype','').split())]
    result=[]
    for scope in scopes:
        ingredients=[]
        for row in scope.properties('recipeIngredient'):
            name=first(row.find(cls='name'));amount=first(row.find(cls='value'));unit=first(row.find(cls='u-unit-name'))
            ingredients.append(f'{name}; {amount}; {unit}' if name and amount and unit else row.text())
        instructions=[]
        for step in scope.properties('recipeInstructions'):
            text_nodes=step.find(prop='text')
            instructions.append(first(text_nodes) if text_nodes else step.text())
        nutrition_scope=scope.properties('nutrition')
        nutrition={}
        if nutrition_scope:
            block=nutrition_scope[0]
            for key in ('calories','proteinContent','fatContent','carbohydrateContent','servingSize'):
                v=first(block.find(prop=key))
                if v:nutrition[key]=v
            if re.search(r'на\s*100\s*(?:г\b|гр|g\b)',block.text(),re.I):nutrition['servingSize']='100 g'
        image=media_url(meta(root,'og:image'),url)
        if not image:
            for node in scope.properties('image'):
                image=media_url(node.attrs.get('src') or node.attrs.get('content') or node.attrs.get('href'),url)
                if image:break
        video=''
        for node in scope.properties('video'):
            raw=first(node.find(prop='contentUrl')) or first(node.find(prop='embedUrl')) or node.attrs.get('content') or node.attrs.get('src')
            video=media_url(raw,url)
            if video:break
        if first(scope.properties('name')) and ingredients:
            result.append({'@type':'Recipe','name':first(scope.properties('name')),'recipeYield':first(scope.properties('recipeYield')),
                           'recipeIngredient':ingredients,'recipeInstructions':instructions,'nutrition':nutrition,
                           'recipeCategory':first(scope.properties('recipeCategory')),'image':image,'video':{'contentUrl':video} if video else None})
    return result


def extract_russianfood(root,url):
    tables=root.find(tag='table',cls='ingr')
    titles=root.find(tag='h1')
    if not tables or not titles:return []
    table=tables[0]
    heading=first(table.find(cls='ingr_title'))
    match=re.search(r'на\s+(\d+)\s+порц',heading,re.I)
    rows=[n for n in table.find(tag='tr') if any(c.startswith('ingr_tr_') for c in n.attrs.get('class','').split())]
    ingredients=[n.text() for n in rows if n.text() and not n.text().endswith(':') and n.text()!='*']
    instructions=[first(n.find(tag='p')) for n in root.find(cls='step_n') if n.find(tag='p')]
    return [{'@type':'Recipe','name':titles[0].text(),'recipeYield':int(match[1]) if match else '',
             'recipeIngredient':ingredients,'recipeInstructions':instructions,'image':media_url(meta(root,'og:image'),url)}]


def extract_html_recipes(markup,url):
    root=Document(markup).root
    recipes=extract_microdata(root,url)
    if recipes:return recipes,'microdata Recipe'
    if (urlsplit(url).hostname or '').lower().removeprefix('www.')=='russianfood.com':
        recipes=extract_russianfood(root,url)
        if recipes:return recipes,'RussianFood HTML'
    return [],''


def saved_source(markup):
    root=Document(markup).root
    canonical=next((n.attrs.get('href','') for n in root.find(tag='link') if n.attrs.get('rel')=='canonical'),'')
    if canonical:return canonical
    og=meta(root,'og:url')
    if og:return og
    match=re.search(r'saved from url=\([^)]*\)([^\s>]+)',markup[:3000],re.I)
    return match[1] if match else ''
