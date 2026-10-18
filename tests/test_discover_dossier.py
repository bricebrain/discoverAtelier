import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import adaptation
import discover_dossier
import discover_podcast_bundle as bundle
from manifeste_validation import ErreurManifeste

RUN = '22222222-2222-4222-8222-222222222222'
NOTE = '3f1d9c6e-8b2a-4c7d-9e10-2a3b4c5d6e7f'
EP = 'a' * 20
OPTIONS = {'coverage': 'condensed', 'level': 'B1', 'style': 'narration', 'targetMinutes': 10, 'faithful': False, 'keepOriginalCopy': False}


def snapshots():
    return [
        {'id': 'd1', 'type': 'episode', 'ref': EP, 'kind': 'episode', 'title': 'Épisode dette', 'language': 'en',
         'capturedAt': '2026-10-19T10:00:00.000Z', 'audioUrl': 'https://example.com/a.mp3'},
        {'id': 'd2', 'type': 'reflection', 'ref': NOTE, 'kind': 'reflection', 'title': 'Ma note', 'language': None,
         'capturedAt': '2026-10-19T10:00:00.000Z', 'text': 'Je pense que la dette publique va baisser dans les prochaines années.'},
        {'id': 'd3', 'type': 'content', 'ref': 'youtube-0123456789abcdef0123', 'kind': 'content', 'title': 'Vidéo préparée',
         'language': 'en', 'capturedAt': '2026-10-19T10:00:00.000Z', 'publicationId': 'pub-1', 'variantKey': 'en-source',
         'segments': [{'id': 's0001', 'text': 'Debt will keep rising, the video argues.', 'startMs': 5000, 'endMs': 9000}]},
    ]


class PreparationDossier(unittest.TestCase):
    def test_assemble_les_sources_avec_leur_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            episode_segments = tmp / 'ep.json'
            episode_segments.write_text(json.dumps({'language': 'en', 'segments': [
                {'id': 's0001', 'text': 'Public debt reached 110 percent of GDP this year.', 'startMs': 61000, 'endMs': 64000}]}))

            def fake_episode(sub, dossier, etape, verifier):
                # Même dossier de cache que la préparation de l'épisode seul.
                self.assertEqual(Path(dossier), tmp / EP)
                return {'segmentsFile': str(episode_segments), 'source': {'language': 'en'}}

            item = {'ref': RUN, 'options': OPTIONS, 'source': {'kind': 'dossier', 'title': 'Dette publique', 'sources': snapshots()}}
            with mock.patch('discover_source.preparer', side_effect=fake_episode):
                result = discover_dossier.preparer(item, tmp / ('dossier-' + RUN), lambda _: None, lambda: None, root=tmp)
            doc = json.loads(Path(result['segmentsFile']).read_text())
        ids = [s['id'] for s in doc['segments']]
        self.assertEqual(ids[0], 'd1-s0001')
        self.assertTrue(any(i.startswith('d2-') for i in ids))
        self.assertEqual(ids[-1], 'd3-s0001')
        first = doc['segments'][0]
        self.assertEqual(first['provenance'], {'sourceId': 'd1', 'segmentId': 's0001', 'startMs': 61000, 'endMs': 64000})
        self.assertEqual((first['startMs'], first['endMs']), (None, None))
        self.assertEqual(first['source'], 'Épisode dette')
        self.assertEqual(doc['language'], 'en')
        self.assertEqual([s['id'] for s in result['dossierSources']], ['d1', 'd2', 'd3'])
        self.assertEqual(result['dossierSources'][2]['publicationId'], 'pub-1')
        self.assertRegex(result['dossierSources'][0]['sha256'], r'^[0-9a-f]{64}$')

    def test_refuse_des_sources_dans_le_desordre(self):
        bad = snapshots()[::-1]
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            discover_dossier.preparer({'ref': RUN, 'options': OPTIONS, 'source': {'kind': 'dossier', 'sources': bad}},
                                      Path(tmp) / 'd', lambda _: None, lambda: None)

    def test_les_consignes_de_synthese_ne_valent_que_pour_le_dossier(self):
        prompts = []

        class Client:
            def demander(self, etape, prompt, *args, **kwargs):
                prompts.append(prompt)
                raise RuntimeError('stop')

        with self.assertRaises(RuntimeError):
            adaptation.generer(Client(), [{'id': 'd1-s1', 'text': 'x', 'source': 'A'}], OPTIONS, dossier=True)
        self.assertIn('SEVERAL independent sources', prompts[-1])
        self.assertIn('"source": "A"', prompts[-1])
        self.assertNotIn('SEVERAL', adaptation.RULES)


class ManifesteDossier(unittest.TestCase):
    def construire(self, provenance_source='d1'):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            segments = tmp / 'segments-source.json'
            segments.write_text(json.dumps({'language': 'en', 'timingSource': 'none', 'segments': [
                {'id': 'd1-s0001', 'text': 'Debt reached 110 percent.', 'startMs': None, 'endMs': None, 'source': 'Épisode',
                 'provenance': {'sourceId': provenance_source, 'segmentId': 's0001', 'startMs': 61000, 'endMs': 64000}},
                {'id': 'd2-s0001', 'text': 'I expect it to fall.', 'startMs': None, 'endMs': None, 'source': 'Note',
                 'provenance': {'sourceId': 'd2', 'segmentId': 's0001', 'startMs': None, 'endMs': None}}]}))
            timings = tmp / 'timings.json'
            timings.write_text(json.dumps([{'id': 'p0001', 'startMs': 0, 'endMs': 1500}]))
            audio = tmp / 'en.mp3'
            audio.write_bytes(b'ID3fake')
            item = {'ref': RUN, 'options': OPTIONS, 'source': {'kind': 'dossier', 'title': 'Dette publique', 'language': 'en', 'category': None}}
            sources = [{'id': f'd{i}', 'type': t, 'ref': r, 'title': 'S', 'capturedAt': '2026-10-19T10:00:00.000Z', 'sha256': 'c' * 64}
                       for i, (t, r) in enumerate([('episode', EP), ('reflection', NOTE)], 1)]
            prepared = {'script': {'segments': [{'id': 'p0001', 'text': 'Debt is high, says the episode, while the note expects a fall.',
                                                 'fr': 'La dette est élevée, selon l’épisode, tandis que la note prévoit une baisse.',
                                                 'speaker': 'Narrator', 'sourceSegments': ['d1-s0001', 'd2-s0001']}], 'keyVocab': []},
                        'generation': {}, 'evaluation': {'verdict': 'ok'}}
            return bundle.construire(item, {'segmentsFile': str(segments), 'audioFile': None, 'dossierSources': sources}, prepared,
                                     {'timingsFile': str(timings), 'file': str(audio), 'durationMs': 1500}, tmp / 'pub')

    def test_manifeste_valide_avec_sources_et_provenance(self):
        manifest, _ = self.construire()
        self.assertEqual(manifest['content']['id'], 'dossier-' + RUN)
        self.assertEqual(manifest['content']['sourceRef'], 'dossier:' + RUN)
        self.assertEqual([s['id'] for s in manifest['content']['sources']], ['d1', 'd2'])
        source = next(v for v in manifest['variants'] if v['kind'] == 'source')
        self.assertNotIn('audio', source)
        self.assertEqual(bundle.content_id({'ref': RUN, 'source': {'kind': 'dossier'}}), 'dossier-' + RUN)

    def test_provenance_vers_une_source_inconnue_refusee(self):
        with self.assertRaises(ErreurManifeste) as ctx:
            self.construire(provenance_source='d5')
        self.assertEqual(ctx.exception.code, 'invalid_provenance')


if __name__ == '__main__':
    unittest.main()
