"""Adaptations : références, publicité, langue, cache d'appels et décisions de relecture."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adaptation
import discover_ai
import discover_review
from discover_evaluation import evaluer, valider_script
from discover_adaptation_schema import PLAN

OPTIONS = {'coverage': 'full', 'level': 'B1', 'style': 'narration', 'targetMinutes': None, 'faithful': False, 'keepOriginalCopy': False}
SOURCES = [{'id': 's1', 'text': 'The company invested 12 million euros in Paris.'},
           {'id': 's2', 'text': 'This is journalistic news about its investment, not a sponsored advertisement.'}]
SCRIPT = {'segments': [{'text': 'The company invested 12 million euros in Paris.', 'fr': 'La société a investi 12 millions d’euros à Paris.',
                        'speaker': 'Narrator', 'sourceSegments': ['s1']}], 'keyVocab': ['investment'], 'tooShortForSubject': False, 'recommendedMinutes': None}


class EvaluationTests(unittest.TestCase):
    def test_facts_grounded_and_language_warnings_are_separate(self):
        e = evaluer(SCRIPT, SOURCES, OPTIONS, {'the', 'company'})
        self.assertEqual(e['verdict'], 'ok')
        self.assertTrue(e['language']['frequentVocabularyAvailable'])
        self.assertGreater(e['language']['uncommonWordRatio'], 0)
        altered = copy.deepcopy(SCRIPT)
        altered['segments'][0]['text'] = 'The company invested 19 million euros in Berlin.'
        e = evaluer(altered, SOURCES, OPTIONS)
        self.assertEqual(e['verdict'], 'review')
        self.assertEqual(e['numbersMissingFromSource'][0]['value'], '19')
        self.assertEqual(e['entitiesMissingFromSource'][0]['value'], 'Berlin')

    def test_citations_french_and_speaker_are_mandatory(self):
        for update in [{'fr': ' '}, {'sourceSegments': []}, {'sourceSegments': ['unknown']}, {'speaker': 'Guest'}]:
            script = copy.deepcopy(SCRIPT)
            script['segments'][0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                valider_script(script, {'s1', 's2'}, 'narration')

    def test_promotion_only_source_never_reaches_writing_or_publication(self):
        class Client:
            def demander(self, stage, prompt, schema, *args, **kwargs):
                if stage == 'plan':
                    return {'summary': 'Advertising', 'speakers': [], 'properNames': [], 'glossary': []}
                if stage.startswith('extract'):
                    return {'items': [{'type': 'promotion', 'text': 'Subscribe now.', 'sourceSegments': ['s1']}]}
                raise AssertionError('No invented script may be written from advertising alone.')
        with self.assertRaisesRegex(ValueError, 'aucun contenu substantiel'):
            adaptation.generer(Client(), [{'id': 's1', 'text': 'Subscribe now.'}], OPTIONS)

    def test_substantial_shortening_of_full_edition_needs_review_even_if_judge_accepts(self):
        sources = [{'id': 's1', 'text': 'word ' * 100}]
        script = copy.deepcopy(SCRIPT)
        script['segments'][0]['text'] = 'word ' * 80
        client = mock.Mock()
        client.demander.return_value = {'verdict': 'ok', 'unsupportedClaims': [], 'omittedKeyPoints': [],
            'lostNuances': [], 'promotionsRemaining': [], 'languageWarnings': [],
            'factChecks': [{'factIndex': 0, 'presentInScript': True, 'reason': 'Present.'}]}
        e = adaptation.juger_script(client, script, sources, OPTIONS, [{'text': 'A fact.', 'sourceSegments': ['s1']}])
        self.assertEqual(e['verdict'], 'review')
        self.assertIn('coverageWarning', e)

    def test_blocks_keep_every_segment_including_middle(self):
        sources = [{'id': str(i), 'text': 'word ' * 500} for i in range(13)]
        blocks = adaptation.blocs(sources)
        self.assertEqual([s['id'] for block in blocks for s in block], [s['id'] for s in sources])
        self.assertTrue(all(sum(len(s['text'].split()) for s in group) <= 1500 for group in blocks))


class ClientTests(unittest.TestCase):
    def test_invalid_response_is_retried_then_cached_without_new_call(self):
        valid = {'summary': 'A river floods.', 'speakers': [], 'properNames': [], 'glossary': []}
        transport = mock.Mock(side_effect=[{'data': {}}, {'data': valid, 'inputTokens': 20, 'outputTokens': 12}])
        with tempfile.TemporaryDirectory() as folder:
            client = discover_ai.Client(folder, config={'key': 'not-a-key', 'model': 'gemini-test', 'judgeModel': 'gemini-test'}, transport=transport)
            self.assertEqual(client.demander('plan', 'prompt', PLAN), valid)
            self.assertEqual(client.demander('plan', 'prompt', PLAN), valid)
            self.assertEqual(transport.call_count, 2)
            self.assertEqual(client.statistiques()['inputTokens'], 20)

    def test_budget_limit_is_not_an_hourly_quota_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            transport = mock.Mock()
            client = discover_ai.Client(folder, config={'key': 'x', 'model': 'test', 'judgeModel': 'test'}, transport=transport)
            client.appels = {str(i): {'inputTokens': 1} for i in range(80)}
            with self.assertRaises(RuntimeError) as raised:
                client.demander('plan', 'prompt', PLAN)
            self.assertNotIsInstance(raised.exception, discover_ai.QuotaAtteint)
            transport.assert_not_called()

    def test_quota_is_not_retried_as_invalid_json(self):
        transport = mock.Mock(side_effect=discover_ai.QuotaAtteint())
        with tempfile.TemporaryDirectory() as folder:
            client = discover_ai.Client(folder, config={'key': 'x', 'model': 'gemini-test', 'judgeModel': 'gemini-test'}, transport=transport)
            with self.assertRaises(discover_ai.QuotaAtteint):
                client.demander('plan', 'prompt', PLAN)
        self.assertEqual(transport.call_count, 1)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'a' / 'prepared-test'
        self.folder.mkdir(parents=True)
        self.source_path = self.root / 'source.json'
        self.source_path.write_text(json.dumps({'segments': SOURCES}))
        self.source = {'segmentsFile': str(self.source_path), 'segmentsSha256': 'source-hash'}
        self.item = {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'source': {'title': 'Title'}, 'options': OPTIONS}
        self.prepared = {'script': copy.deepcopy(SCRIPT), 'evaluation': {'verdict': 'review'}, 'generation': {}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_auto_publication_marks_flagged_version_and_keeps_report(self):
        self.prepared['evaluation']['verdict'] = 'review'
        discover_review.exiger(self.item, self.prepared, self.source, self.folder)
        self.assertTrue(self.prepared['evaluation']['autoPublished'])
        self.assertTrue((Path(self.folder) / 'review.json').exists())

    def test_no_auto_publication_then_explicit_approval_bound_to_exact_text(self):
        with self.assertRaises(discover_review.RelectureRequise):
            discover_review.exiger(self.item, self.prepared, self.source, self.folder, automatique=False)
        review = json.loads((self.folder / 'review.json').read_text())
        discover_review.action(self.root, {'id': self.item['id'], 'signature': review['signature'], 'action': 'approve'})
        discover_review.exiger(self.item, self.prepared, self.source, self.folder, automatique=False)
        self.assertTrue(self.prepared['evaluation']['acceptedByUser'])
        self.prepared['script']['segments'][0]['text'] += ' Another claim.'
        with self.assertRaises(discover_review.RelectureRequise):
            discover_review.exiger(self.item, self.prepared, self.source, self.folder, automatique=False)

    def test_rejected_cannot_be_approved_and_editing_cannot_invent_references(self):
        self.prepared['evaluation']['verdict'] = 'rejected'
        with self.assertRaises(discover_review.RelectureRequise):
            discover_review.exiger(self.item, self.prepared, self.source, self.folder, automatique=False)
        review = json.loads((self.folder / 'review.json').read_text())
        with self.assertRaises(ValueError):
            discover_review.action(self.root, {'id': self.item['id'], 'signature': review['signature'], 'action': 'approve'})
        edited = copy.deepcopy(SCRIPT['segments'])
        edited[0]['sourceSegments'] = ['invented']
        with self.assertRaises(ValueError):
            discover_review.action(self.root, {'id': self.item['id'], 'signature': review['signature'], 'action': 'edit', 'segments': edited})

    def test_new_outside_target_duration_requires_its_own_approval(self):
        with self.assertRaises(discover_review.RelectureRequise):
            discover_review.exiger(self.item, self.prepared, self.source, self.folder, automatique=False)
        review = json.loads((self.folder / 'review.json').read_text())
        discover_review.action(self.root, {'id': self.item['id'], 'signature': review['signature'], 'action': 'approve'})
        self.prepared['evaluation']['durationOutsideTarget'] = {'targetMinutes': 12, 'actualMinutes': 17}
        with self.assertRaises(discover_review.RelectureRequise):
            discover_review.exiger(self.item, self.prepared, self.source, self.folder, automatique=False)
        review = json.loads((self.folder / 'review.json').read_text())
        discover_review.action(self.root, {'id': self.item['id'], 'signature': review['signature'], 'action': 'approve'})
        discover_review.exiger(self.item, self.prepared, self.source, self.folder, automatique=False)

    def test_invalid_faithful_edit_leaves_script_untouched(self):
        self.prepared['faithful'] = [{'id': 's1', 'text': 'Source translation.'}]
        with self.assertRaises(discover_review.RelectureRequise):
            discover_review.exiger(self.item, self.prepared, self.source, self.folder, automatique=False)
        review = json.loads((self.folder / 'review.json').read_text())
        with self.assertRaises(ValueError):
            discover_review.action(self.root, {'id': self.item['id'], 'signature': review['signature'], 'action': 'edit',
                'segments': SCRIPT['segments'], 'faithful': [{'id': 'unknown', 'text': 'Edited.'}]})
        self.assertFalse((self.folder / 'edited.json').exists())
        self.assertFalse((self.folder / 'action.json').exists())
