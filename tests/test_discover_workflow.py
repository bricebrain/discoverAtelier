"""Chaîne complète : une relecture bloque l'audio/publication ; la durée est corrigée avant publication."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover_preparation as workflow
import discover_review
import discover_queue
import discover_cible
from discover_ai import QuotaAtteint


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        source_path = self.root / 'segments.json'
        source_path.write_text(json.dumps({'segments': [{'id': 's001', 'text': 'A fact.'}]}))
        self.source = {'segmentsFile': str(source_path), 'segmentsSha256': 'hash'}
        self.item = {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'ref': 'a' * 20, 'leaseToken': 'token',
                     'source': {'title': 'Episode'}, 'options': {'coverage': 'condensed', 'targetMinutes': 12, 'level': 'B1', 'style': 'narration', 'faithful': False, 'keepOriginalCopy': False}}
        self.prepared = {'script': {'segments': [{'text': 'A fact.', 'fr': 'Un fait.', 'speaker': 'Narrator', 'sourceSegments': ['s001']}], 'tooShortForSubject': False, 'recommendedMinutes': None, 'keyVocab': []},
                         'evaluation': {'verdict': 'ok'}, 'generation': {}, 'facts': []}
        self.client = mock.Mock()
        self.client.statistiques.return_value = {}

    def tearDown(self):
        self.tmp.cleanup()

    def test_review_cannot_start_tts_or_publish(self):
        self.prepared['evaluation']['verdict'] = 'review'
        with mock.patch.object(workflow.adaptation, 'generer', return_value=self.prepared), \
                mock.patch.object(workflow.discover_vocabulary, 'charger', return_value=set()), \
                mock.patch.object(workflow.discover_audio, 'executer') as audio, \
                mock.patch.object(workflow.discover_cible, 'publier_manifeste') as publish:
            with self.assertRaises(discover_review.RelectureRequise):
                workflow.preparer(self.item, self.source, self.root, lambda _: None, lambda: None, {}, self.client)
            audio.assert_not_called()
            publish.assert_not_called()

    def test_actual_duration_is_corrected_before_publication(self):
        with mock.patch.object(workflow.adaptation, 'generer', return_value=self.prepared), \
                mock.patch.object(workflow.discover_vocabulary, 'charger', return_value=set()), \
                mock.patch.object(workflow.discover_audio, 'calibrer', return_value={'bf_emma': .7}), \
                mock.patch.object(workflow.discover_audio, 'executer', side_effect=[{'durationMs': 18*60_000}, {'durationMs': 12*60_000}]) as audio, \
                mock.patch.object(workflow.discover_cible, 'requete', side_effect=discover_cible.ErreurDiscover(404, 'not_found')), \
                mock.patch.object(workflow, 'construire', return_value=({}, {})), \
                mock.patch.object(workflow.discover_cible, 'publier_manifeste', return_value={'status': 'ready'}) as publish:
            workflow.preparer(self.item, self.source, self.root, lambda _: None, lambda: None, {}, self.client)
            self.assertEqual(audio.call_count, 2)
            self.assertAlmostEqual(audio.call_args_list[1].args[-1]['bf_emma'], 1.05)
            self.assertEqual(publish.call_args.kwargs['demande'], self.item)

    def test_consumer_releases_review_without_marking_failure(self):
        request = mock.Mock(return_value={})
        worker = discover_queue.FileDiscover(self.root, requete=request, preparer=mock.Mock(return_value=self.source),
                                             transformer=mock.Mock(side_effect=discover_review.RelectureRequise()))
        worker.item, worker.config = self.item, {}
        worker._traiter()
        last = request.call_args_list[-1]
        self.assertTrue(last.args[2].endswith('/release'))
        self.assertEqual(last.args[3]['stage'], 'review')
        self.assertFalse(any(c.args[2].endswith('/fail') for c in request.call_args_list))

    def test_quota_returns_item_without_penalty_and_keeps_intermediates(self):
        worker = discover_queue.FileDiscover(self.root, preparer=mock.Mock(return_value=self.source), transformer=mock.Mock(side_effect=QuotaAtteint()))
        worker.item, worker.config, worker.owner = self.item, {}, 'mac'
        def request(config, method, path, data):
            if path.endswith('/release'):
                worker.stop.set()
            return {}
        worker.requete = mock.Mock(side_effect=request)
        worker._executer()
        self.assertTrue(any(c.args[2].endswith('/release') for c in worker.requete.call_args_list))
        self.assertFalse(any(c.args[2].endswith('/fail') for c in worker.requete.call_args_list))
        self.assertTrue(Path(self.source['segmentsFile']).exists())
