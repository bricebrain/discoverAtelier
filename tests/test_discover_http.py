import io
import json
import unittest
from unittest import mock

import discover_http


class Gestionnaire:
    def __init__(self, path, headers=None):
        self.path = path
        self.headers = {'Host': '127.0.0.1:53782', **(headers or {})}
        self.rfile = io.BytesIO()
        self.reponses = []

    def _envoyer(self, status, corps, mime=None):
        self.reponses.append((status, corps))


class RoutesDiscover(unittest.TestCase):
    def test_episodes_transmet_les_filtres(self):
        h = Gestionnaire('/api/discover/episodes?category=news&show=bbc&inconnu=x')
        with mock.patch.object(discover_http.FILE, 'requete', return_value={'episodes': []}) as requete, \
                mock.patch.object(discover_http.FILE, 'config', {'workerUrl': 'x'}):
            discover_http.traiter(h, 'GET', '/api/discover/episodes')
        self.assertEqual(h.reponses, [(200, {'episodes': []})])
        chemin = requete.call_args.args[2]
        self.assertTrue(chemin.startswith('/atelier/episodes?'))
        self.assertIn('category=news', chemin)
        self.assertNotIn('inconnu', chemin)

    def test_un_bug_renvoie_une_erreur_json(self):
        h = Gestionnaire('/api/discover/shows')
        with mock.patch.object(discover_http.FILE, 'requete', side_effect=KeyError('x')), \
                mock.patch.object(discover_http.FILE, 'config', {'workerUrl': 'x'}), \
                mock.patch('traceback.print_exc'):
            discover_http.traiter(h, 'GET', '/api/discover/shows')
        self.assertEqual(h.reponses[0][0], 500)
        self.assertIn('erreur', h.reponses[0][1])


if __name__ == '__main__':
    unittest.main()
