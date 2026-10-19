import io
import unittest
from email.message import Message

import discover_articles as articles

PAGE = '''<html><head><title>Hypemen | World news | The Guardian</title>
<meta property="og:title" content="The hypemen redefining Afrobeats"></head><body>
<nav><p>Skip to main content and other navigation links for this site.</p></nav>
<article>
<p>Style of emceeing based on high-octane vocals has flourished thanks to its unique way of captivating crowds.</p>
<figure><figcaption><p>Shang performing in Lagos last year, during a packed show downtown.</p></figcaption></figure>
<p>“Even my mother calls me Shang now,” the 32-year-old said in an interview near the university campus.</p>
<p>Read more: how Afrobeats conquered the world, from Lagos to London and beyond the stage.</p>
<p>Related stories about the music scene in West Africa</p>
<p>Hypemen are now a permanent fixture on the entertainment scene, and festivals book them weeks ahead. Get the newsletter!</p>
<p>Are student protests being manipulated ahead of the election?</p>
</article><footer><p>© 2026 Guardian News &amp; Media Limited or its affiliated companies.</p></footer></body></html>'''


class Reponse:
    def __init__(self, corps, url='https://www.theguardian.com/world/x', ctype='text/html; charset=utf-8'):
        self.corps, self.url = corps.encode(), url
        self.headers = Message()
        self.headers['Content-Type'] = ctype

    def read(self, n):
        return self.corps[:n]

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Extraction(unittest.TestCase):
    def test_garde_le_corps_de_l_article_et_ecarte_le_reste(self):
        titre, texte, paywall = articles.extraire(PAGE)
        self.assertEqual(titre, 'The hypemen redefining Afrobeats')
        self.assertFalse(paywall)
        paragraphes = texte.split('\n\n')
        self.assertEqual(len(paragraphes), 3)
        self.assertTrue(paragraphes[0].startswith('Style of emceeing'))
        self.assertTrue(paragraphes[-1].startswith('Hypemen are now'))
        self.assertNotIn('Read more', texte)
        self.assertNotIn('Shang performing', texte)
        self.assertNotIn('navigation', texte)
        self.assertNotIn('newsletter', texte)
        self.assertNotIn('manipulated', texte)

    def test_article_reserve_aux_abonnes(self):
        page = PAGE.replace('</head>', '<script type="application/ld+json">{"isAccessibleForFree": false}</script></head>')
        resultat = articles.recuperer('https://www.lemonde.fr/x', ouvrir=lambda req, timeout: Reponse(page, 'https://www.lemonde.fr/x'))
        self.assertEqual(resultat['status'], 'partial')

    def test_page_complete_courte_ou_illisible(self):
        long_page = PAGE.replace('</article>', ''.join(f'<p>Paragraph number {i} adds enough real substance to the article body.</p>' for i in range(10)) + '</article>')
        self.assertEqual(articles.recuperer('https://www.theguardian.com/x', ouvrir=lambda r, timeout: Reponse(long_page))['status'], 'complete')
        self.assertEqual(articles.recuperer('https://www.lemonde.fr/live', ouvrir=lambda r, timeout: Reponse('<html><body><div id=app></div></body></html>'))['status'], 'unavailable')

    def test_refuse_le_reseau_local_et_les_redirections_vers_lui(self):
        self.assertEqual(articles.recuperer('http://192.168.1.10/admin')['status'], 'unavailable')
        self.assertEqual(articles.recuperer('https://example.com/a', ouvrir=lambda r, timeout: Reponse(PAGE, 'http://localhost/x'))['status'], 'unavailable')

    def test_traite_les_demandes_en_attente(self):
        appels = []

        def requete(config, methode, chemin, data=None):
            appels.append((methode, chemin, data))
            if methode != 'GET':
                return {}
            if chemin == '/atelier/article-fetches':
                return {'items': [{'id': '11111111-1111-4111-8111-111111111111', 'url': 'https://www.theguardian.com/world/x'}]}
            return {'items': [{'id': 'a' * 20, 'url': 'https://www.theguardian.com/world/y'}, {'id': '../x', 'url': 'https://x.org'}]}

        n = articles.traiter_en_attente({}, requete, ouvrir=lambda r, timeout: Reponse(PAGE))
        self.assertEqual(n, 2)
        posts = [a for a in appels if a[0] == 'POST']
        self.assertEqual([p[1] for p in posts], ['/atelier/article-fetches/11111111-1111-4111-8111-111111111111', '/atelier/article-texts/' + 'a' * 20])
        self.assertEqual(posts[0][2]['status'], 'partial')


if __name__ == '__main__':
    unittest.main()
