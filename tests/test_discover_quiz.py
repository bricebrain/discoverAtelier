"""Quiz local : génération simulée, cache, publication réelle du paquet et comptabilité."""
import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover_quiz
import discover_preparation as workflow
import discover_costs
from discover_ai import Client, FournisseurIndisponible
from manifeste_validation import contrats, valider_manifeste

QUESTIONS = json.loads((contrats() / 'fixtures/quiz.json').read_text())
SCRIPT = {'segments': [{'text': 'The city will add buses to reduce traffic next month.',
                       'fr': 'La ville ajoutera des bus le mois prochain.', 'speaker': 'Narrator',
                       'sourceSegments': ['s001']}], 'keyVocab': []}


class QuizTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.transport = mock.Mock(return_value={'data': {'questions': QUESTIONS}, 'inputTokens': 1000, 'outputTokens': 500})
        self.client = Client(self.root / 'cache', config={'model': 'test-model'}, transport=self.transport)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_identifie_texte_final_et_niveau(self):
        for _ in range(2):
            self.assertEqual(discover_quiz.generer(self.client, SCRIPT, 'B1', {}), QUESTIONS)
        self.transport.assert_called_once()
        self.assertTrue(next(iter(self.client.appels.values()))['cached'])
        discover_quiz.generer(self.client, SCRIPT, 'A2', {})
        edited = copy.deepcopy(SCRIPT)
        edited['segments'][0]['text'] += ' Changed.'
        discover_quiz.generer(self.client, edited, 'B1', {})
        self.assertEqual(self.transport.call_count, 3)
        self.assertIn('CEFR level A2', self.transport.call_args_list[1].args[0])

    def test_desactivation_et_reponse_invalide_ou_panne(self):
        self.assertEqual(discover_quiz.generer(self.client, SCRIPT, 'B1', {'comprehensionQuiz': False}), [])
        self.transport.assert_not_called()
        self.transport.return_value['data'] = {'questions': [{**q, 'segmentIndex': 1} for q in QUESTIONS]}
        with mock.patch('builtins.print'):
            self.assertEqual(discover_quiz.generer(self.client, SCRIPT, 'B1', {}), [])
            self.transport.side_effect = FournisseurIndisponible('test')
            self.assertEqual(discover_quiz.generer(self.client, SCRIPT, 'B1', {}), [])

    def test_validation_du_fixture_et_rejets(self):
        self.assertEqual(discover_quiz.valider(QUESTIONS, 1), QUESTIONS)
        invalid = [[], QUESTIONS[:2], [{**q, 'correctChoice': True} for q in QUESTIONS],
                   [{**q, 'choices': ['A', ' a ', 'C']} for q in QUESTIONS],
                   [{**q, 'explanation': ' '} for q in QUESTIONS],
                   [{**q, 'segmentIndex': -1} for q in QUESTIONS],
                   [{**q, 'segmentIndex': 1} for q in QUESTIONS]]
        import jsonschema
        for questions in invalid:
            with self.subTest(questions=questions), self.assertRaises((ValueError, jsonschema.ValidationError)):
                discover_quiz.valider(questions, 1)

    def test_preparation_simulee_publie_trois_questions_et_cout(self):
        item = {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'ref': 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb',
                'source': {'kind': 'reflection', 'language': 'fr', 'title': 'Transport'},
                'options': {'coverage': 'full', 'targetMinutes': None, 'level': 'B1', 'style': 'narration',
                            'faithful': False, 'keepOriginalCopy': False}}
        source_path = self.root / 'source.json'
        source_path.write_text(json.dumps({'timingSource': 'none', 'segments': [{'id': 's001', 'text': 'La ville ajoute des bus.'}]}))
        source = {'segmentsFile': str(source_path)}
        audio = self.root / 'audio.mp3'
        audio.write_bytes(b'fake-audio')
        timings = self.root / 'timings.json'
        timings.write_text('[{"id":"p0001","startMs":0,"endMs":1000}]')
        speech = mock.Mock(provider='deepgram')
        speech.generate.return_value = {'file': str(audio), 'timingsFile': str(timings), 'durationMs': 1000,
                                       'origin': 'deepgram', 'timingSource': 'deepgram'}
        root = self.root / 'episode'
        prepared = {'script': copy.deepcopy(SCRIPT), 'evaluation': {'verdict': 'ok'}, 'generation': {}}
        def publish(manifest, paths, **kwargs):
            valider_manifeste(manifest)
            adapted = next(v for v in manifest['variants'] if v['kind'] == 'adaptation')
            self.assertEqual(adapted['quiz'], QUESTIONS)
            self.assertEqual(adapted['generation']['calls'], 1)
            return {'status': 'ready', 'publicationId': 'simulee'}
        with mock.patch.object(workflow.adaptation, 'generer', return_value=prepared), \
                mock.patch.object(workflow.discover_vocabulary, 'charger', return_value=set()), \
                mock.patch.object(workflow.discover_speech, 'Session', return_value=speech), \
                mock.patch.object(workflow.discover_cible, 'requete', side_effect=workflow.discover_cible.ErreurDiscover(404, 'not_found')), \
                mock.patch.object(workflow.discover_cible, 'publier_manifeste', side_effect=publish):
            workflow.preparer(item, source, root, lambda _: None, lambda: None, {}, self.client)
        row = discover_costs.rapport(self.root, {})['preparations'][0]
        self.assertEqual(row['quizUsd'], .003)
        self.assertEqual(row['geminiUsd'], row['quizUsd'])

    def test_paquet_ecarte_quiz_invalide_sans_bloquer(self):
        from test_discover_prepared import PreparedBundleTests
        fixture = PreparedBundleTests()
        fixture.setUp()
        try:
            fixture.prepared['quiz'] = [{**q, 'segmentIndex': 200} for q in QUESTIONS]
            manifest, _ = workflow.construire(fixture.item, fixture.source, fixture.prepared, fixture.audio, fixture.root / 'pub')
            self.assertNotIn('quiz', manifest['variants'][1])
        finally:
            fixture.tearDown()

    def test_registre_existant_migre_et_cout_quiz_inclus_une_seule_fois(self):
        registre = discover_costs.Registre(self.root)
        # Reconstitue un registre antérieur à Q.
        with sqlite3.connect(registre.path) as db:
            db.execute('ALTER TABLE preparations DROP COLUMN quiz_micro')
        db.close()
        registre = discover_costs.Registre(self.root)
        appels = {'q': {'stage': 'quiz', 'provider': 'openai', 'model': 'gpt-5-mini', 'inputTokens': 1000, 'outputTokens': 500}}
        for _ in range(2):
            registre.enregistrer({'id': 'x', 'options': {}}, appels, self.root)
        registre.enregistrer({'id': 'x', 'options': {}}, {k: {**v, 'cached': True} for k, v in appels.items()}, self.root)
        row = discover_costs.rapport(self.root, {})['preparations'][0]
        self.assertEqual(row['quizUsd'], .00125)
        self.assertEqual(row['openaiUsd'], .00125)
        self.assertEqual(len(registre.dernieres()), 1)
