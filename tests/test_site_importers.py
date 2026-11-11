from pathlib import Path
import tempfile
import unittest
from importing import import_html,parse_page,parse_ingredient
from storage import save_recipes,load_recipes

FIXTURES=Path(__file__).parent/'fixtures'

class SiteImporterTests(unittest.TestCase):
    def test_povar_microdata_and_per100g_nutrition_not_treated_as_per_serving(self):
        r=import_html(FIXTURES/'povar-microdata.html')[0]
        self.assertEqual(r.name,'Неожиданные спагетти с коньяком')
        self.assertEqual(r.servings,4)
        self.assertEqual(len(r.ingredients),8)
        self.assertEqual(len(r.method.splitlines()),6)
        self.assertIsNone(r.kcal)
        self.assertIsNone(r.protein)
        self.assertEqual(r.source_nutrition_per100g,{'kcal':299,'protein':6,'fat':19,'carbs':23})
        self.assertTrue(r.image_url.startswith('https://img.povar.ru/'))
        self.assertIn('microdata',r.import_notes[0])
        self.assertEqual(r.ingredients[2].unit,'шт')

    def test_russianfood_cp1251_portions_steps_and_explicit_garlic_weight(self):
        r=import_html(FIXTURES/'russianfood.html')[0]
        self.assertEqual(r.name,'Гречка по-купечески с фаршем')
        self.assertEqual(r.servings,5)
        self.assertEqual(len(r.ingredients),12)
        self.assertEqual(len(r.method.splitlines()),15)
        garlic=next(i for i in r.ingredients if i.name=='Чеснок')
        self.assertEqual((garlic.amount,garlic.unit),(5,'г'))
        self.assertIn('1 крупный зубчик',garlic.original)
        self.assertIsNone(next(i for i in r.ingredients if i.name=='Соль').amount)
        self.assertEqual(r.source_url,'https://www.russianfood.com/recipes/recipe.php?rid=164509')
        self.assertIsNone(r.source_nutrition_per100g)
        self.assertTrue(r.image_url.startswith('https://'))

    def test_source_metadata_survives_storage(self):
        r=import_html(FIXTURES/'povar-microdata.html')[0]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'recipes.json';save_recipes(path,[r]);restored=load_recipes(path)[0]
            self.assertEqual(restored.source_nutrition_per100g,r.source_nutrition_per100g)
            self.assertEqual(restored.image_url,r.image_url)

    def test_other_jsonld_source_keeps_photo_and_video(self):
        markup='<script type="application/ld+json">{"@type":"Recipe","name":"Тест","image":{"url":"https://example.com/photo.jpg"},"video":{"embedUrl":"https://example.com/video"},"recipeIngredient":["100 г рис"],"recipeYield":2}</script>'
        r=parse_page(markup,'https://example.com/recipe')[0]
        self.assertEqual(r.image_url,'https://example.com/photo.jpg')
        self.assertEqual(r.video_url,'https://example.com/video')

    def test_russian_quantity_annotations(self):
        for raw,name,amount,unit in [('Лук - 100 г (1 средний)','Лук',100,'г'),('Чеснок - 1 крупный зубчик (5 г)','Чеснок',5,'г'),('Сахар - 1 щепотка','Сахар',1,'щепотка'),('Мука; 1; ст. ложка','Мука',1,'ст. л.')]:
            i=parse_ingredient(raw);self.assertEqual((i.name,i.amount,i.unit),(name,amount,unit))
        self.assertIsNone(parse_ingredient('Мука - 1-2 стакана').amount)

    def test_microdata_title_does_not_take_nested_author_name(self):
        markup='<main itemscope itemtype="https://schema.org/Recipe"><div itemprop="author" itemscope itemtype="https://schema.org/Person"><span itemprop="name">Автор</span></div><h1 itemprop="name">Суп</h1><span itemprop="recipeYield">2</span><span itemprop="recipeIngredient">100 г рис</span><div itemprop="recipeInstructions" itemscope itemtype="https://schema.org/HowToStep"><span itemprop="text">Сварить.</span></div></main>'
        r=parse_page(markup,'https://example.com/recipe')[0]
        self.assertEqual(r.name,'Суп')
        self.assertEqual(r.method,'Сварить.')

    def test_russianfood_optional_table_closing_tags_do_not_duplicate_rows(self):
        markup='<h1>Суп</h1><table class="ingr"><tr><td class="ingr_title">Продукты (на 2 порции)<tr class="ingr_tr_0"><td>Рис - 100 г<tr class="ingr_tr_1"><td>Вода - 500 мл</table><div class="step_n"><p>Сварить.</p></div>'
        r=parse_page(markup,'https://www.russianfood.com/recipes/recipe.php?rid=1')[0]
        self.assertEqual(len(r.ingredients),2)
        self.assertEqual([(i.name,i.amount) for i in r.ingredients],[('Рис',100),('Вода',500)])
