"""Contrat et panne partielle du pont : aucun transport ou moteur réel."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover_englishfluency as bridge
import discover_preparation as workflow
from discover_podcast_bundle import variant_key

CONFIG = {'englishFluency': {'enabled': True, 'workerUrl': 'https://english.example',
                            'apiSecret': 'SECRET-NE-JAMAIS-JOURNALISER', 'profileId': 'default'}}


class TransportFactice:
    def __init__(self):
        self.calls, self.audios, self.contents = [], {}, {}
        self.failure = None

    def __call__(self, config, path, data=None, fichier=None):
        self.calls.append(path)
        if path.startswith('/content/audio?'):
            if self.failure == 'audio':
                raise OSError(config['apiSecret'])
            params = parse_qs(urlsplit(path).query)
            key = params['key'][0]
            self.audios[key] = Path(fichier).read_bytes()
            return {'ok': True, 'key': key}
        if self.failure == 'content':
            raise OSError(config['apiSecret'])
        self.contents[data['id']] = copy.deepcopy(data)  # vrai contrat : upsert
        if self.failure == 'lost_response':
            raise OSError('réponse perdue après commit')
        return {'ok': True}


class PontTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'prepared-test'
        self.folder.mkdir()
        self.config = copy.deepcopy(CONFIG)
        (self.folder / 'published.json').write_text('{"status":"ready"}')
        self.audio = self.root / 'audio.mp3'
        self.audio.write_bytes(b'mp3-factice')
        self.doc = self.root / 'segments.json'
        self.doc.write_text(json.dumps({'keyVocab': ['fact', 'fact'], 'segments': [
            {'id': 'p0001', 'text': 'A fact.', 'fr': 'Un fait.', 'startMs': 0, 'endMs': 1000}]}))
        self.key = 'en-full-b1'
        self.manifest = {'content': {'id': 'podcast-abc', 'title': 'Un épisode', 'sourceType': 'podcast',
                                   'sourceUrl': 'https://publisher.example/audio.mp3', 'originalLanguage': 'fr', 'category': 'science'},
                         'variants': [{'key': self.key, 'language': 'en', 'kind': 'adaptation', 'cefrLevel': 'B1',
                                       'segmentsFile': 'segments/en.json', 'audio': {'source': 'r2', 'file': 'audio/en.mp3',
                                       'origin': 'deepgram', 'timingSource': 'deepgram', 'durationMs': 1000}}],
                         'files': {'segments/en.json': {'sha256': bridge.empreinte_fichier(self.doc)}, 'audio/en.mp3': {'sha256': bridge.empreinte_fichier(self.audio), 'size': self.audio.stat().st_size}}}
        self.paths = {'segments/en.json': str(self.doc), 'audio/en.mp3': str(self.audio)}
        self.transport = TransportFactice()
        self.addCleanup(mock.patch.stopall)
        mock.patch('socket.create_connection', side_effect=AssertionError('Réseau interdit pendant ces tests')).start()

    def publier(self):
        return bridge.publier(self.manifest, self.paths, self.key, self.folder, self.config, self.transport)

    def test_paquet_bilingue_v2_et_audio_local(self):
        self.assertEqual(self.publier()['status'], 'published')
        payload = next(iter(self.transport.contents.values()))
        self.assertEqual((payload['type'], payload['profileId'], payload['body']), ('podcast', 'default', 'A fact.'))
        meta = payload['metadata']
        self.assertEqual((meta['schemaVersion'], meta['textEn'], meta['textFr']), (2, 'A fact.', 'Un fait.'))
        self.assertEqual(meta['segments'], [{'id': 'p0001', 'en': 'A fact.', 'fr': 'Un fait.', 'startMs': 0, 'endMs': 1000}])
        self.assertEqual(meta['keyVocab'], ['fact'])
        self.assertEqual(meta['chunks'], [])  # aucun sens français inventé
        self.assertEqual(meta['audioLanguage'], 'en')
        self.assertEqual(meta['language'], 'en')
        self.assertEqual(meta['audioOrigin'], 'deepgram')
        self.assertTrue(meta['listeningAvailable'])
        self.assertEqual(self.transport.audios[payload['audioR2Key']], b'mp3-factice')
        packet = (self.folder / 'englishfluency-packet.json').read_text()
        self.assertNotIn(self.config['englishFluency']['apiSecret'], packet)
        self.assertNotIn(str(self.root), json.dumps(payload))

    def test_deuxieme_execution_ne_fait_aucun_envoi(self):
        self.publier()
        calls = list(self.transport.calls)
        self.publier()
        bridge.reprendre(self.folder, self.config, self.transport)
        self.assertEqual(self.transport.calls, calls)
        self.assertEqual(len(self.transport.contents), 1)

    def test_reprise_echec_audio_contenu_et_reponse_perdue(self):
        for failure in ('audio', 'content', 'lost_response'):
            with self.subTest(failure=failure):
                (self.folder / 'englishfluency-state.json').unlink(missing_ok=True)
                self.transport.failure = failure
                self.assertEqual(self.publier()['status'], 'failed')
                state = (self.folder / 'englishfluency-state.json').read_text()
                self.assertNotIn('SECRET', state)
                self.transport.failure = None
                # Simuler le nettoyage des pending après 24 h : le même audio est restauré.
                self.transport.audios.clear()
                self.assertEqual(bridge.reprendre(self.folder, self.config, self.transport)['status'], 'published')
                self.assertEqual(len(self.transport.contents), 1)
                self.assertEqual(len(self.transport.audios), 1)

    def test_perte_du_checkpoint_ne_duplique_pas(self):
        self.publier()
        (self.folder / 'englishfluency-state.json').unlink()
        bridge.reprendre(self.folder, self.config, self.transport)
        self.assertEqual(len(self.transport.contents), 1)
        self.assertEqual(len(self.transport.audios), 1)

    def test_revisions_meme_id_variantes_profils_distincts(self):
        packet = bridge.construire(self.manifest, self.paths, self.key, 'default')
        changed = copy.deepcopy(self.manifest)
        changed['content']['title'] = 'Titre corrigé'
        revised = bridge.construire(changed, self.paths, self.key, 'default')
        self.assertEqual(packet['payload']['id'], revised['payload']['id'])
        self.assertNotEqual(packet['payload']['metadata']['contentRevision'], revised['payload']['metadata']['contentRevision'])
        other = bridge.construire(self.manifest, self.paths, self.key, '__global__')
        self.assertNotEqual(packet['payload']['id'], other['payload']['id'])
        changed['variants'][0]['key'] = 'en-full-b2'
        other = bridge.construire(changed, self.paths, 'en-full-b2', 'default')
        self.assertNotEqual(packet['payload']['id'], other['payload']['id'])
        self.publier()
        self.manifest['content']['title'] = 'Correction'
        self.publier()
        self.assertEqual(len(self.transport.contents), 1)
        self.assertEqual(next(iter(self.transport.contents.values()))['title'], 'Correction')

    def test_desactive_par_defaut_sans_acces_fichiers_ni_transport(self):
        self.assertEqual(bridge.publier({}, {}, '', '/inexistant', {}, self.transport), {'status': 'disabled'})
        self.config['englishFluency']['enabled'] = False
        self.assertEqual(bridge.reprendre('/inexistant', self.config, self.transport), {'status': 'disabled'})
        self.assertEqual(self.transport.calls, [])

    def test_refuse_discover_non_publie_ou_destination_modifiee(self):
        (self.folder / 'published.json').write_text('{"status":"failed"}')
        with self.assertRaises(ValueError):
            self.publier()
        self.assertEqual(self.transport.calls, [])
        (self.folder / 'published.json').write_text('{"status":"ready"}')
        self.publier()
        self.config['englishFluency']['profileId'] = 'autre'
        with self.assertRaises(ValueError):
            bridge.reprendre(self.folder, self.config, self.transport)

    def test_audio_modifie_refuse_et_texte_seul_sans_timings(self):
        self.audio.write_bytes(b'autre-audio')
        with self.assertRaises(ValueError):
            self.publier()
        self.manifest['variants'][0].pop('audio')
        self.assertEqual(self.publier()['status'], 'published')
        payload = next(iter(self.transport.contents.values()))
        self.assertIsNone(payload['audioR2Key'])
        self.assertIsNone(payload['metadata']['segments'][0]['startMs'])
        self.assertFalse(payload['metadata']['listeningAvailable'])

    def test_transport_http_factice_et_refus_redirection(self):
        connection = mock.Mock()
        response = connection.getresponse.return_value
        response.status, response.read.return_value = 200, b'{"ok":true}'
        target = bridge.destination(self.config)
        with mock.patch.object(bridge.http.client, 'HTTPSConnection', return_value=connection):
            self.assertEqual(bridge.requete(target, '/content', data={'id': 'x'}), {'ok': True})
            headers = connection.request.call_args.kwargs['headers']
            self.assertEqual(headers['Authorization'], 'Bearer ' + target['apiSecret'])
            response.status = 302
            with self.assertRaises(RuntimeError):
                bridge.requete(target, '/content', data={})
        connection.close.assert_called()

    def test_texte_modifie_depuis_discover_refuse(self):
        self.doc.write_text('{"segments":[]}')
        with self.assertRaises(ValueError):
            self.publier()
        self.assertEqual(self.transport.calls, [])

    def test_reprise_refuse_audio_modifie_sans_envoi(self):
        self.transport.failure = 'content'
        self.publier()
        self.audio.write_bytes(b'copie-modifiee')
        self.transport.calls.clear()
        self.assertEqual(bridge.reprendre(self.folder, self.config, self.transport)['status'], 'failed')
        self.assertEqual(self.transport.calls, [])

    def test_commande_locale_reprend_le_paquet_sans_discover(self):
        self.transport.failure = 'content'
        self.publier()
        config_path = self.root / 'config-test.json'
        config_path.write_text(json.dumps(self.config))
        self.transport.failure = None
        with mock.patch.object(sys, 'argv', ['discover_englishfluency.py', str(self.folder), '--config', str(config_path)]), \
                mock.patch.object(bridge, 'requete', self.transport), mock.patch('builtins.print'):
            self.assertEqual(bridge.main(), 0)
        self.assertEqual(len(self.transport.contents), 1)

    def test_preparation_simulee_publie_discover_malgre_panne_du_pont(self):
        options = {'coverage': 'full', 'targetMinutes': None, 'level': 'B1', 'style': 'narration',
                   'faithful': False, 'keepOriginalCopy': False}
        item = {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'ref': 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb',
                'leaseToken': 'factice', 'source': {'kind': 'reflection', 'language': 'fr', 'title': 'Note'}, 'options': options}
        source_file = self.root / 'source.json'
        source_file.write_text(json.dumps({'timingSource': 'none', 'segments': [{'id': 's001', 'text': 'Un fait.'}]}))
        source = {'segmentsFile': str(source_file)}
        timings = self.root / 'timings.json'
        timings.write_text('[{"id":"p0001","startMs":0,"endMs":1000}]')
        prepared = {'script': {'segments': [{'text': 'A fact.', 'fr': 'Un fait.', 'sourceSegments': ['s001']}],
                              'keyVocab': ['fact']}, 'evaluation': {'verdict': 'ok'}, 'generation': {}}
        client = mock.Mock(appels={})
        client.statistiques.return_value = {}
        speech = mock.Mock(provider='deepgram')
        speech.generate.return_value = {'file': str(self.audio), 'timingsFile': str(timings), 'durationMs': 1000,
                                        'origin': 'deepgram', 'timingSource': 'deepgram'}
        result = {'status': 'ready', 'publicationId': 'publication-factice'}
        self.transport.failure = 'content'
        def publish(*args, **kwargs):
            self.assertEqual(self.transport.calls, [])  # Discover précède toujours le pont
            return result
        with mock.patch.object(workflow.adaptation, 'generer', return_value=prepared), \
                mock.patch.object(workflow.discover_vocabulary, 'charger', return_value=set()), \
                mock.patch.object(workflow.discover_review, 'exiger'), \
                mock.patch.object(workflow.discover_speech, 'Session', return_value=speech), \
                mock.patch.object(workflow.discover_cible, 'requete', side_effect=workflow.discover_cible.ErreurDiscover(404, 'not_found')), \
                mock.patch.object(workflow.discover_cible, 'publier_manifeste', side_effect=publish) as discover, \
                mock.patch.object(bridge, 'requete', self.transport), mock.patch('builtins.print'):
            self.assertEqual(workflow.preparer(item, source, self.root, lambda _: None, lambda: None, self.config, client), result)
        folder = self.root / ('prepared-' + workflow.empreinte(options)[:16])
        self.assertEqual(json.loads((folder / 'published.json').read_text()), result)
        self.assertEqual(json.loads((folder / 'englishfluency-state.json').read_text())['status'], 'failed')
        self.transport.failure = None
        self.assertEqual(bridge.reprendre(folder, self.config, self.transport)['status'], 'published')
        payload = next(iter(self.transport.contents.values()))
        self.assertEqual(payload['metadata']['discoverVariantKey'], variant_key(options))
        self.assertEqual(payload['metadata']['keyVocab'], ['fact'])
        discover.assert_called_once()
        # Même une exception avant l'envoi (configuration, paquet ou disque) reste isolée.
        self.transport.calls.clear()
        with mock.patch.object(workflow.adaptation, 'generer', return_value=prepared), \
                mock.patch.object(workflow.discover_vocabulary, 'charger', return_value=set()), \
                mock.patch.object(workflow.discover_review, 'exiger'), \
                mock.patch.object(workflow.discover_speech, 'Session', return_value=speech), \
                mock.patch.object(workflow.discover_cible, 'requete', side_effect=workflow.discover_cible.ErreurDiscover(404, 'not_found')), \
                mock.patch.object(workflow.discover_cible, 'publier_manifeste', return_value=result), \
                mock.patch.object(bridge, 'publier', side_effect=OSError('disque indisponible')), mock.patch('builtins.print'):
            self.assertEqual(workflow.preparer(item, source, self.root, lambda _: None, lambda: None, self.config, client), result)


if __name__ == '__main__':
    unittest.main()
