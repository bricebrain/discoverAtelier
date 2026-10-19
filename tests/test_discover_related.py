"""Rapprochements : aucun accès réseau réel ni fournisseur payant."""
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import discover_related as related
from discover_related_store import Store
from discover_related_similarity import calculate, fingerprint, text
from discover_related_judge import Judge
from discover_related_calibrer import export, evaluate


def item(i, title=None, date='2026-10-19T10:00:00Z', language='en', publisher=None):
    return {'type': 'article', 'id': str(i), 'title': title or f'News Paris {i}', 'excerpt': 'President Macron visits Paris.',
            'language': language, 'publishedAt': date, 'publisher': publisher or str(i)}


class RelatedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = [item(1), item(2)]
        self.posts = []
        self.encoder = Mock(side_effect=lambda texts, cfg: [[1., 0.] for _ in texts])
        self.config = {'relatedLlm': False}

    def worker(self, config, method, path, data=None):
        if method == 'POST':
            self.posts.append(data)
            return {'ok': True}
        if path == '/atelier/queue':
            return {'items': []}
        return {'items': self.data, 'nextCursor': 2}

    def run_pass(self, now=10000, **kw):
        with patch.object(related.os, 'nice', return_value=5):
            return related.run(self.root, self.config, self.worker, encoder=self.encoder, now=now, **kw)

    def test_fingerprint_cache_model_and_text(self):
        self.run_pass()
        self.assertEqual(self.encoder.call_count, 1)
        count = len(self.posts)
        self.run_pass(11000)
        self.assertEqual(self.encoder.call_count, 1)
        self.assertEqual(len(self.posts), count)
        self.config['relatedModel'] = 'other'
        self.run_pass(12000)
        self.assertEqual(self.encoder.call_count, 2)
        self.data[0]['title'] = 'New title'
        self.run_pass(13000)
        self.assertEqual(len(self.encoder.call_args.args[0]), 1)

    def test_clean_duplicate_text_encoded_once(self):
        self.data = [item(1, '<b>Same</b>'), item(2, 'Same')]
        self.run_pass()
        self.assertEqual(len(self.encoder.call_args.args[0]), 1)
        self.assertFalse(any(s['neighbors'] for p in self.posts for s in p['sources']))
        self.assertLessEqual(len(text({'title': 'a'*2000})), 900)

    def test_offline_and_busy_and_interval(self):
        self.encoder.side_effect = OSError('down')
        self.assertIn('skipped', self.run_pass())
        self.assertEqual(self.posts, [])
        self.assertIn('skipped', self.run_pass(10001))
        self.assertEqual(self.encoder.call_count, 1)
        self.assertIn('skipped', self.run_pass(12000, busy=True))
        request = Mock(return_value={'items': [{'status': 'leased'}]})
        with patch.object(related.os, 'nice', return_value=5):
            self.assertIn('skipped', related.run(self.root, {}, request, now=13000))
        self.assertEqual(request.call_count, 1)

    def test_window_cross_language_doubt_and_candidates(self):
        a, b, archive = item(1), item(2, language='fr'), item(3, date='2020-01-01T00:00:00Z')
        rows = [(str(i), x, str(i), [1, 0]) for i, x in enumerate([a, b, archive])]
        judge = Mock(return_value=True)
        sources, groups = calculate(rows, {}, judge)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]['members']), 2)
        self.assertTrue(groups[0]['dossierCandidate'])
        self.assertFalse(judge.called)
        a['title'], a['excerpt'] = 'a quiet story', 'plain words'
        b['title'], b['excerpt'] = 'another story', 'different words'
        calculate(rows[:2], {}, judge)
        self.assertEqual(judge.call_count, 1)

    def test_llm_cap_cache_cost_and_disable(self):
        store = Store(self.root)
        self.addCleanup(store.close)
        client = Mock()
        client.demander.return_value = {'sameEvent': True}
        client.appels = {'a': {'provider': 'gemini', 'model': 'gemini-3.1-flash-lite', 'inputTokens': 100, 'outputTokens': 10}}
        factory = Mock(return_value=client)
        judge = Judge(store, self.root, {'relatedLlm': True, 'relatedLlmDailyCap': 1}, lambda: None, factory)
        self.assertTrue(judge(item(1), item(2), 'a', 'b'))
        self.assertTrue(judge(item(2), item(1), 'b', 'a'))
        self.assertFalse(judge(item(2), item(3), 'b', 'c'))
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(related.status(self.root)['llmCallsToday'], 1)
        self.assertGreater(related.status(self.root)['llmCostTodayUsd'], 0)
        self.assertFalse(Judge(store, self.root, {'relatedLlm': False}, lambda: None, factory)(item(1), item(2), 'a', 'b'))

    def test_publish_retry_and_group_deletion(self):
        failures = [True]
        def request(*args):
            if args[1] == 'POST' and failures and failures.pop():
                raise OSError('cut')
            return self.worker(*args)
        with patch.object(related.os, 'nice', return_value=5):
            with self.assertRaises(OSError):
                related.run(self.root, {}, request, encoder=self.encoder, now=10000)
        self.run_pass(11000)
        store = Store(self.root)
        self.assertEqual(len(store.get('groups')), 1)
        store.close()
        self.data[1]['deleted'] = True
        self.run_pass(12000)
        self.assertTrue(any(g['members'] == [] for p in self.posts for g in p['groups']))

    def test_embed_contract(self):
        response = Mock()
        response.read.return_value = json.dumps({'embeddings': [[.5, .2]]}).encode()
        opener = MagicMock()
        opener.return_value.__enter__.return_value = response
        with patch.object(related.urllib.request, 'urlopen', opener):
            self.assertEqual(related.embed(['text'], {}), [[.5, .2]])
        req = opener.call_args.args[0]
        self.assertEqual(req.full_url, 'http://localhost:11434/api/embed')
        self.assertEqual(json.loads(req.data)['keep_alive'], '2m')

    def test_calibration_csv(self):
        self.run_pass()
        path = self.root / 'pairs.csv'
        export(self.root, path)
        with path.open(encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['meme_evenement'], '')
        rows[0]['meme_evenement'] = 'oui'
        with path.open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            evaluate(path)
        self.assertIn('précision', output.getvalue())


class RelatedBoundariesTests(unittest.TestCase):
    def test_thresholds_languages_and_evidence(self):
        import math
        for language, score, expected in [('fr', .65, 1), ('en', .65, 0), ('en', .73, 1)]:
            a, b = item(1), item(2, language=language)
            rows = [('a', a, 'fa', [1, 0]), ('b', b, 'fb', [score, math.sqrt(1-score*score)])]
            _, groups = calculate(rows, {}, lambda *args: False)
            self.assertEqual(len(groups), expected)

    def test_batches_and_resume_after_200(self):
        with tempfile.TemporaryDirectory() as root:
            data = [item(i) for i in range(205)]
            def worker(config, method, path, body=None):
                if path == '/atelier/queue':
                    return {'items': []}
                if method == 'GET':
                    return {'items': data[:200], 'nextCursor': 200}
                return {'ok': True}
            encoder = Mock(side_effect=lambda values, cfg: [[1., 0.] for _ in values])
            # Écarter le calcul du graphe pour concentrer le test sur la borne des lots.
            with patch.object(related.os, 'nice', return_value=5), patch.object(related, 'calculate', return_value=([], [])):
                related.run(root, {}, worker, encoder=encoder, now=10000)
            self.assertEqual(sum(len(c.args[0]) for c in encoder.call_args_list), 200)
            self.assertTrue(all(len(c.args[0]) <= 16 for c in encoder.call_args_list))
            store = Store(root)
            self.assertEqual(store.get('cursor'), 200)
            store.close()

    def test_restoration_invalidates_outgoing_incoming_and_group_ack(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            a = item(1)
            store.put(a, 'fa')
            source = {'type': 'article', 'id': '1', 'neighbors': []}
            incoming = {'type': 'episode', 'id': '2', 'neighbors': [{'targetType': 'article', 'targetId': '1', 'score': .8}]}
            group = {'groupId': 'g', 'members': [{'type': 'article', 'id': '1'}]}
            store.ack('source:article:1', source)
            store.ack('source:episode:2', incoming)
            store.ack('group:g', group)
            store.put({**a, 'seq': 999}, 'fa')
            self.assertTrue(store.changed('source:article:1', source))
            self.assertTrue(store.changed('source:episode:2', incoming))
            self.assertTrue(store.changed('group:g', group))
            store.close()

    def test_pair_budget_resumes_before_publication(self):
        import discover_related_pairs as pairs
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            rows = [(str(i), item(i), str(i), [1., 0.]) for i in range(4)]
            self.assertEqual(pairs.prepare(store, rows, lambda: None, limit=2), (False, 2, 6))
            self.assertEqual(pairs.prepare(store, rows, lambda: None, limit=2), (False, 4, 6))
            self.assertEqual(pairs.prepare(store, rows, lambda: None, limit=2), (True, 6, 6))
            self.assertEqual(len(list(pairs.scores(store))), 6)
            store.close()
