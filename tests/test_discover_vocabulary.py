import json
from pathlib import Path
import copy
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import discover_vocabulary_picks as vocabulary


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{'id': str(i), 'seq': i, 'status': 'pending', 'word': 'word',
                      'sentence': 'A word.', 'contentId': 'content', 'publicationId': 'publication',
                      'variantKey': 'en-source', 'segmentIndex': 0, 'language': 'en'} for i in range(1, 4)]
        self.receipts = {}
        self.calls = 0
        self.destination = {'profileId': 'default'}

    def discover(self, config, method, path, data=None):
        if method == 'GET':
            after = int(parse_qs(urlsplit(path).query).get('after', ['0'])[0])
            rows = [copy.deepcopy(r) for r in self.rows if r['seq'] > after]
            return {'picks': rows[:2], 'nextAfter': rows[1]['seq'] if len(rows) > 2 else None}
        row = next(r for r in self.rows if r['id'] == path.split('/')[-2])
        row.update(data)
        return {'pick': row}

    def ef(self, config, path, data=None):
        self.calls += 1
        self.assertEqual(path, '/words/picks')
        return self.receipts.setdefault(data['sourceId'], {'ok': True, 'status': 'sent', 'wordId': 'word'})

    def sync(self, transport=None, ef=None):
        return vocabulary.synchroniser({}, transport or self.discover, ef or self.ef, self.destination)

    def test_second_passage_sans_doublon_et_pagination(self):
        self.assertEqual(self.sync()['sent'], 3)
        self.assertEqual(self.sync()['sent'], 0)
        self.assertEqual(self.calls, 3)

    def test_echec_ef_sans_perte_et_reprise(self):
        def fail(*args, **kwargs):
            raise RuntimeError('secret distant')
        self.assertEqual(self.sync(ef=fail)['failed'], 3)
        self.assertEqual(len(self.rows), 3)
        self.assertNotIn('secret', str(self.rows))
        self.assertEqual(self.sync()['sent'], 3)

    def test_perte_accuse_rejoue_meme_identifiant(self):
        def transport(config, method, path, data=None):
            if method == 'POST':
                raise OSError('accusé perdu')
            return self.discover(config, method, path, data)
        self.assertEqual(self.sync(transport=transport)['unacknowledged'], 3)
        self.assertEqual(len(self.receipts), 3)
        self.assertEqual(self.sync()['sent'], 3)
        self.assertEqual(len(self.receipts), 3)

    def test_reponse_ef_invalide_n_est_pas_un_succes(self):
        self.assertEqual(self.sync(ef=lambda *a, **k: {'ok': True, 'status': 'sent'})['failed'], 3)

    def test_acces_existants_du_pont(self):
        config = {'englishFluency': {'workerUrl': 'https://example.test', 'apiSecret': 'existing'}}
        self.assertEqual(vocabulary.cible(config)['apiSecret'], 'existing')

    def test_repli_config_import(self):
        with patch('bundles.charger_config_import', return_value=({'workerUrl': 'https://example.test', 'apiSecret': 'existing'}, None)):
            self.assertEqual(vocabulary.cible({})['profileId'], 'default')

    def test_contrat_partage_avec_workers(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/vocabulary-pick.json').read_text())
        self.rows = [{**fixture, 'id': fixture['sourceId'].split(':')[1], 'seq': 1, 'status': 'pending'}]
        def ef(config, path, data=None):
            self.assertEqual(data, fixture)
            return {'ok': True, 'status': 'already_known', 'wordId': 'known'}
        self.assertEqual(self.sync(ef=ef)['already_known'], 1)
