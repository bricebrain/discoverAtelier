import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import discover_cible
import discover_http


class Gestionnaire:
    def __init__(self, path, headers=None):
        self.path = path
        self.headers = {'Host': '127.0.0.1:53782', **(headers or {})}
        self.rfile = io.BytesIO()
        self.close_connection = False
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


def poster(path, corps):
    brut = json.dumps(corps).encode()
    h = Gestionnaire(path, {'Origin': 'http://127.0.0.1:53782', 'X-Discover-Atelier': '1', 'Content-Length': str(len(brut))})
    h.rfile = io.BytesIO(brut)
    return h


class Suppressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        publiee = self.root / 'abcdefabcdefabcdef01' / 'prepared-b1'
        publiee.mkdir(parents=True)
        (publiee / 'published.json').write_text('{}')
        (publiee / 'review.json').write_text('{}')
        (self.root / 'abcdefabcdefabcdef01' / 'prepared-b2').mkdir()  # préparation pas encore publiée : gardée
        (self.root / 'abcdefabcdefabcdef01' / 'source.json').write_text('{}')

    def tearDown(self):
        self.tmp.cleanup()

    def appeler(self, path, corps, **requete):
        h = poster(path, corps)
        with mock.patch.object(discover_http.FILE, 'requete', **requete) as appel, \
                mock.patch.object(discover_http.FILE, 'config', {'workerUrl': 'x'}), \
                mock.patch.object(discover_http.FILE, 'dossier', self.root):
            discover_http.traiter(h, 'POST', path)
        return h, appel

    def test_supprime_le_contenu_et_les_versions_locales_publiees(self):
        h, appel = self.appeler('/api/discover/delete-content', {'contentId': 'podcast-abcdefabcdefabcdef01', 'kind': 'episode', 'ref': 'abcdefabcdefabcdef01'}, return_value={})
        self.assertEqual(h.reponses[0], (200, {'ok': True, 'localVersions': 1}))
        self.assertEqual(appel.call_args.args[1:3], ('DELETE', '/atelier/contents/podcast-abcdefabcdefabcdef01'))
        dossier = self.root / 'abcdefabcdefabcdef01'
        self.assertFalse((dossier / 'prepared-b1').exists())
        self.assertTrue((dossier / 'prepared-b2').exists())
        self.assertTrue((dossier / 'source.json').exists())

    def test_deja_supprime_dans_l_app_nettoie_quand_meme(self):
        h, _ = self.appeler('/api/discover/delete-content', {'contentId': 'podcast-abcdefabcdefabcdef01', 'kind': 'episode', 'ref': 'abcdefabcdefabcdef01'},
                            side_effect=discover_cible.ErreurDiscover(404, 'not_found'))
        self.assertEqual(h.reponses[0][0], 200)
        self.assertFalse((self.root / 'abcdefabcdefabcdef01' / 'prepared-b1').exists())

    def test_refuse_un_chemin_hors_file(self):
        self.assertEqual(discover_http.effacer_versions_locales(self.root, 'episode', '../../etc'), 0)
        h, appel = self.appeler('/api/discover/delete-content', {'contentId': '../x'}, return_value={})
        self.assertEqual(h.reponses[0][0], 503)
        appel.assert_not_called()

    def test_retirer_une_demande_active_explique_quoi_faire(self):
        h, _ = self.appeler('/api/discover/remove', {'id': '0' * 8 + '-0000-0000-0000-' + '0' * 12},
                            side_effect=discover_cible.ErreurDiscover(409, 'queue_active'))
        self.assertEqual(h.reponses[0], (503, {'erreur': 'Annule d’abord la préparation en cours.'}))


class PreparationAutomatique(unittest.TestCase):
    def appeler(self, path, corps):
        h = poster(path, corps)
        with mock.patch.object(discover_http.FILE, 'requete', return_value={'show': {'id': 'edito-eco'}, 'enabled': False}) as appel, \
                mock.patch.object(discover_http.FILE, 'config', {'workerUrl': 'x'}):
            discover_http.traiter(h, 'POST', path)
        return h, appel

    def test_reglage_d_une_emission_transmis_au_worker(self):
        h, appel = self.appeler('/api/discover/show-auto', {'id': 'edito-eco', 'autoPrepare': True, 'autoPreset': 'condensed8', 'autoLevel': 'B1', 'autre': 1})
        self.assertEqual(h.reponses[0][0], 200)
        self.assertEqual(appel.call_args.args[1:], ('PATCH', '/atelier/shows/edito-eco', {'autoPrepare': True, 'autoPreset': 'condensed8', 'autoLevel': 'B1'}))
        h, appel = self.appeler('/api/discover/show-auto', {'id': '../x'})
        self.assertEqual(h.reponses[0][0], 503)
        appel.assert_not_called()

    def test_interrupteur_general(self):
        h, appel = self.appeler('/api/discover/auto-setting', {'enabled': False})
        self.assertEqual(appel.call_args.args[1:], ('PUT', '/atelier/settings/auto-prepare', {'enabled': False}))
        h, appel = self.appeler('/api/discover/auto-setting', {'enabled': 'non'})
        appel.assert_not_called()


if __name__ == '__main__':
    unittest.main()
