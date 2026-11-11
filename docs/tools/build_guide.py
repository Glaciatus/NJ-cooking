"""Build the offline HTML and printable PDF from USER_GUIDE_RU.md.

Documentation-only dependencies: pandoc, Python playwright and Chromium.
Run from any directory: python docs/tools/build_guide.py
Override the browser binary with GUIDE_CHROMIUM if necessary.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
from playwright.sync_api import sync_playwright

DOCS=Path(__file__).resolve().parents[1]
html_path=DOCS/'USER_GUIDE_RU.html'
subprocess.run(['pandoc',str(DOCS/'USER_GUIDE_RU.md'),'--from','gfm','--to','html5','--standalone','--embed-resources',
    '--resource-path='+str(DOCS),'--css',str(DOCS/'guide.css'),'--toc','--toc-depth=2',
    '--metadata','title=Семейное меню 0.8.1 — инструкция пользователя','--metadata','lang=ru',
    '--output',str(html_path)],check=True)
html=html_path.read_text()
# Keep the visible title once and place navigation after the introduction.
html=re.sub(r'<header id="title-block-header">.*?</header>','',html,flags=re.S)
toc=re.search(r'<nav id="TOC".*?</nav>',html,re.S)
if toc:
    navigation=toc.group(0)
    html=html[:toc.start()]+html[toc.end():]
    html=html.replace('<h2',navigation+'\n<h2',1)
# Short ASCII PDF named destinations work across PDF viewers. Visible headings
# stay Russian; only browser anchor identifiers change in this generated file.
for n,identifier in enumerate(re.findall(r'\bid="([^"]+)"',html),1):
    if not identifier.isascii():
        replacement=f'section-{n}'
        html=html.replace(f'id="{identifier}"',f'id="{replacement}"').replace(f'href="#{identifier}"',f'href="#{replacement}"')
html_path.write_text(html)
executable=os.environ.get('GUIDE_CHROMIUM')
if not executable:
    executable='/usr/lib/chromium/chromium' if Path('/usr/lib/chromium/chromium').exists() else shutil.which('chromium')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=executable,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    page=browser.new_page(viewport={'width':1360,'height':900})
    page.set_content(html,wait_until='load')
    assert page.locator('img').count()==13
    assert page.locator('img').evaluate_all('(imgs)=>imgs.every(i=>i.complete && i.naturalWidth>0)')
    page.pdf(path=str(DOCS/'USER_GUIDE_RU.pdf'),print_background=True,prefer_css_page_size=True,tagged=True,outline=True,
        display_header_footer=True,header_template='<span></span>',
        footer_template='<div style="width:100%;font-size:8px;color:#61738a;text-align:center">Семейное меню 0.8.1 · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
    # Check both desktop and narrow reading without network resources.
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.set_viewport_size({'width':390,'height':844})
    assert page.locator('img').evaluate_all('(imgs)=>imgs.every(i=>i.getBoundingClientRect().width<=innerWidth)')
    browser.close()
print('Built USER_GUIDE_RU.html and USER_GUIDE_RU.pdf; all 13 screenshots loaded.')
