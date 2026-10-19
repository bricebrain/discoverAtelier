"""Dossier : vraie orchestration, vraie synthèse et vrai paquet, services externes simulés."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from discover_queue import BailPerdu

from discover_simulation import EPISODE, VIDEO, QUESTIONS, Simulation
from manifeste_validation import valider_provenance, valider_segments


class DossierBoutEnBout(unittest.TestCase):
    def test_file_bail_sources_synthese_paquet_et_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim = Simulation(Path(tmp), 'dossier').executer()
            self.assertTrue(sim.worker.ready, sim.consumer.message)
            events = sim.worker.events
            self.assertEqual(events[0][:2], ('POST', '/atelier/queue/lease'))
            stages = [data['stage'] for _, path, data in events if path.endswith('/heartbeat')]
            self.assertEqual(stages, ['download', 'normalize', 'transcribe', 'download', 'normalize',
                                      'transcribe', 'transcribe', 'transcribe', 'plan', 'extract',
                                      'adapt', 'evaluate', 'tts', 'publish'])
            self.assertEqual(sim.media, [('episode', EPISODE), ('youtube', 'youtube-' + VIDEO)])
            manifest = sim.worker.manifest
            self.assertEqual([s['id'] for s in manifest['content']['sources']], ['d1', 'd2', 'd3', 'd4', 'd5'])
            self.assertIn('City News', manifest['content']['sources'][3]['title'])
            self.assertEqual(manifest['content']['sources'][4]['publicationId'], 'previous-publication')
            source = next(v for v in manifest['variants'] if v['kind'] == 'source')
            adapted = next(v for v in manifest['variants'] if v['kind'] == 'adaptation')
            self.assertNotIn('audio', source)
            original = json.loads(sim.worker.uploads[source['segmentsFile']])
            final = json.loads(sim.worker.uploads[adapted['segmentsFile']])
            source_ids = {s['id'] for s in original['segments']}
            valider_segments(final, adapted, source_ids)
            valider_provenance(original, {'d1', 'd2', 'd3', 'd4', 'd5'}, True)
            self.assertEqual({r for s in final['segments'] for r in s['sourceSegments']}, source_ids)
            self.assertEqual(original['segments'][0]['provenance'],
                             {'sourceId': 'd1', 'segmentId': 's0001', 'startMs': 0, 'endMs': 10_000})
            self.assertIsNone(original['segments'][2]['provenance']['startMs'])
            self.assertEqual(original['segments'][4]['provenance']['startMs'], 500)
            plan = sim.ai.prompts[0]
            self.assertIn('SEVERAL independent sources', plan)
            self.assertIn('state the disagreement explicitly', plan)
            self.assertIn('Personal note (personal note)', plan)
            self.assertIn('Article (article, City News)', plan)
            self.assertNotIn('provenance', plan)
            self.assertEqual(adapted['quiz'], QUESTIONS)
            publication_events = [(method, path) for method, path, _ in events if '/publications' in path]
            self.assertEqual(publication_events[0], ('POST', '/atelier/publications'))
            self.assertEqual(publication_events[-1], ('POST', '/atelier/publications/simulation/commit'))
            self.assertEqual(sum(method == 'PUT' for method, _ in publication_events), len(manifest['files']))
            self.assertEqual(sum(path.endswith('/commit') for _, path in publication_events), 1)
            self.assertFalse(any(path.endswith(('/fail', '/release')) for _, path, _ in events))
            self.assertNotIn(sim.worker.token, json.dumps(sim.consumer.etat()))
            self.assertIsNone(json.loads((Path(tmp) / 'state.json').read_text())['item'])
            published = list(Path(tmp).glob('dossier-*/prepared-*/published.json'))
            self.assertEqual(len(published), 1)
            self.assertEqual(json.loads(published[0].read_text())['status'], 'ready')
            self.assertEqual(sim.costs['preparations'][0]['quizUsd'], .003)

    def test_bail_perdu_avant_publication_interdit_toute_ecriture_distante(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim = Simulation(Path(tmp), 'dossier')
            sim.worker.lose_lease_at = 'publish'
            with self.assertRaises(AssertionError) as error:
                sim.executer()
            self.assertIsInstance(error.exception.__cause__, BailPerdu)
            self.assertIsNone(sim.worker.manifest)
            self.assertEqual(sim.worker.uploads, {})
            self.assertFalse(any('/publications' in path or path.endswith('/fail')
                                 for _, path, _ in sim.worker.events))
            self.assertFalse(list(Path(tmp).glob('dossier-*/prepared-*/published.json')))

    def test_source_indisponible_ne_publie_pas_un_dossier_partiel(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim = Simulation(Path(tmp), 'dossier')
            sim.source_media = mock.Mock(side_effect=RuntimeError('Source simulée inaccessible'))
            with self.assertRaises(AssertionError) as error:
                sim.executer()
            self.assertEqual(str(error.exception.__cause__), 'Source simulée inaccessible')
            self.assertEqual(sim.ai.prompts, [])
            self.assertFalse(sim.worker.ready)
            self.assertIsNone(sim.worker.manifest)
            self.assertTrue(any(path.endswith('/fail') for _, path, _ in sim.worker.events))
