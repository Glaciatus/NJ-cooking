import json
import unittest
from email.message import Message
from unittest.mock import patch, MagicMock
from importing import parse_page, parse_ingredient, import_url, public_url, ImportFailure, schema_number


def page(recipe):
    return '<html><script type="application/ld+json">' + json.dumps(recipe, ensure_ascii=False) + '</script></html>'

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.recipe = {'@type':'Recipe', 'name':'Рис с яйцом', 'recipeYield':'4 servings',
                       'recipeIngredient':['400 г рис', 'Яйцо — 2 шт', 'Соль по вкусу'],
                       'recipeInstructions':[{'@type':'HowToSection','itemListElement':[{'@type':'HowToStep','text':'<b>Сварить</b> рис.'}]}],
                       'nutrition':{'calories':'500 kcal','proteinContent':'20 g','fatContent':'10 g','carbohydrateContent':'70 g'}}

    def test_graph_import_source_steps_and_nutrition(self):
        r = parse_page(page({'@graph':[self.recipe]}), 'https://example.com/recipe')[0]
        self.assertEqual(r.name, 'Рис с яйцом')
        self.assertEqual(r.servings, 4)
        self.assertEqual(r.kcal, 500)
        self.assertEqual(r.protein, 20)
        self.assertEqual(r.source_url, 'https://example.com/recipe')
        self.assertEqual(r.method, 'Сварить рис.')
        self.assertFalse(r.reviewed)
        self.assertEqual(r.ingredients[0].amount, 400)
        self.assertIsNone(r.ingredients[2].amount)
        self.assertTrue(r.import_notes)

    def test_multiple_recipes_and_malformed_blocks(self):
        second = {**self.recipe, 'name':'Второе блюдо'}
        html = '<script type="application/ld+json">bad</script>' + page([self.recipe, second])
        self.assertEqual(len(parse_page(html, 'https://example.com')), 2)

    def test_ambiguous_serving_basis_and_yield_not_guessed(self):
        self.recipe['recipeYield'] = '12 cookies'
        self.recipe['nutrition']['servingSize'] = '100 g'
        r = parse_page(page(self.recipe), 'https://example.com')[0]
        self.assertIsNone(r.servings)
        self.assertIsNone(r.kcal)
        self.assertIsNone(r.protein)

    def test_missing_nutrition_is_not_import_failure(self):
        del self.recipe['nutrition']
        del self.recipe['recipeYield']
        r = parse_page(page(self.recipe), 'https://example.com')[0]
        self.assertIsNone(r.kcal)
        self.assertIsNone(r.servings)

    def test_ingredient_formats_and_ambiguous_ranges(self):
        for text, amount, unit in [('1 1/2 cups rice', 1.5, 'cup'), ('½ кг рис', .5, 'кг'), ('Рис; 0,4; кг', .4, 'кг'), ('рис 100 г',100,'г')]:
            i = parse_ingredient(text)
            self.assertEqual((i.amount, i.unit), (amount, unit), text)
        for text in ('рис 1–2 г', '1-2 cups rice', 'по вкусу', 'немного соли'):
            self.assertIsNone(parse_ingredient(text).amount, text)

    def test_energy_units(self):
        self.assertAlmostEqual(schema_number('418.4 kJ', energy=True), 100)
        self.assertEqual(schema_number('500 mg'), .5)
        self.assertIsNone(schema_number('500 per recipe', energy=True))

    def test_unsupported_and_invalid_links(self):
        with self.assertRaisesRegex(ImportFailure, 'Recipe'):
            parse_page('<html>Нет рецепта</html>', 'https://example.com')
        for url in ('file:///etc/passwd', 'javascript:alert(1)', 'https://u:p@example.com', 'http://127.0.0.1', 'http://[::1]', 'http://localhost', ''):
            with self.subTest(url=url), self.assertRaises(ImportFailure):
                public_url(url)

    @patch('urllib.request.build_opener')
    def test_download_pipeline_redirect_source(self, build):
        response = MagicMock()
        response.geturl.return_value = 'https://example.com/final'
        response.headers = Message()
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.read.return_value = page(self.recipe).encode()
        build.return_value.open.return_value.__enter__.return_value = response
        result = import_url('https://example.com/start')
        self.assertEqual(result[0].source_url, 'https://example.com/final')
        self.assertEqual(build.return_value.open.call_args.kwargs['timeout'], 15)

class WordImportTests(unittest.TestCase):
    def write_word(self, path, paragraphs):
        import zipfile
        from xml.sax.saxutils import escape
        content = ''
        for text, style in paragraphs:
            properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
            content += f'<w:p>{properties}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+content+'</w:body></w:document>')

    def test_multi_recipe_document_heading_sections_and_missing_servings(self):
        from importing import import_docx
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as f:
            name=f.name
        try:
            self.write_word(name, [('Рис','Heading1'),('Порций: 4',''),('Ингредиенты','Heading2'),('Рис — 400 г',''),
                                   ('Приготовление','Heading2'),('Сварить рис',''),('Яичница','Heading1'),
                                   ('Продукты:',''),('Яйцо; 2; шт',''),('Приготовление:',''),('Пожарить','')])
            recipes=import_docx(name)
            self.assertEqual([r.name for r in recipes],['Рис','Яичница'])
            self.assertEqual(recipes[0].servings,4)
            self.assertIsNone(recipes[1].servings)
            self.assertEqual(recipes[0].ingredients[0].amount,400)
            self.assertEqual(recipes[1].method,'Пожарить')
        finally:
            from pathlib import Path
            Path(name).unlink()

    def test_plain_paragraph_titles_detected_and_unknown_text_retained(self):
        from importing import import_docx
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            name=Path(d)/'r.docx'
            self.write_word(name, [(line,'') for line in ['Суп','Порций: 4','Ингредиенты','100 г рис','Приготовление','Сварить','Каша','Порций: 2','Продукты','Овсяные хлопья; 200; г']])
            self.assertEqual([r.name for r in import_docx(name)],['Суп','Каша'])
            self.write_word(name,[('Рецепт без разметки',''),('Произвольный состав и приготовление','')])
            self.assertIn('Произвольный состав',import_docx(name)[0].method)
