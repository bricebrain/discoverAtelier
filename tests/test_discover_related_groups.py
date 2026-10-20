"""Cohérence événementielle : une chaîne de liens ne suffit pas à former un groupe."""
import hashlib
import csv
import io
import itertools
import math
import tempfile
import unittest
from unittest.mock import Mock, patch

from discover_related import publish
from discover_related_groups import coherent_groups
from discover_related_calibrer import evaluate, FIELDS
from discover_related_similarity import calculate
from discover_related_store import Store


def rows(publishers=None, dates=None, languages=None):
    return [(key, {'type': 'article', 'id': key, 'title': f'News Paris {key.upper()}',
                   'publisher': (publishers or {}).get(key, key),
                   'publishedAt': (dates or {}).get(key, '2026-10-20T12:00:00Z'),
                   'language': (languages or {}).get(key, 'en')}, key, [1., 0.])
            for key in ('a', 'b', 'c')]


def members(groups):
    return [tuple(m['id'] for m in group['members']) for group in groups]


class CoherentGroupsTests(unittest.TestCase):
    def test_chain_keeps_valid_pairs_without_unproven_endpoint_link(self):
        self.assertEqual(coherent_groups('abc', [('a', 'b', .8), ('b', 'c', .9)]), [['a', 'b'], ['b', 'c']])

    def test_complete_triangle_and_isolated_item(self):
        self.assertEqual(coherent_groups('abcd', [('a', 'b', .9), ('b', 'c', .8), ('a', 'c', .75)]),
                         [['a', 'b', 'c']])

    def test_two_cliques_cannot_merge_through_one_bridge(self):
        links = [('a', 'b', .95), ('c', 'd', .96), ('b', 'c', .8)]
        self.assertEqual(coherent_groups('abcd', links), [['a', 'b'], ['b', 'c'], ['c', 'd']])

    def test_order_direction_and_equal_scores_do_not_change_groups(self):
        links = [('a', 'b', .8), ('b', 'c', .8)]
        for order in itertools.permutations(links):
            for keys in ('abc', 'cba'):
                self.assertEqual(coherent_groups(keys, order), [['a', 'b'], ['b', 'c']])
                self.assertEqual(coherent_groups(keys, [(b, a, score) for a, b, score in order]), [['a', 'b'], ['b', 'c']])

    def test_duplicate_links_use_strongest_score_and_ignore_self_link(self):
        links = [('a', 'b', .7), ('b', 'a', .95), ('b', 'c', .9), ('a', 'a', 1.)]
        self.assertEqual(coherent_groups('abc', links), [['a', 'b'], ['b', 'c']])

    def test_all_returned_pairs_are_proven_on_many_graph_shapes(self):
        candidates = list(itertools.combinations('abcd', 2))
        for mask in range(1 << len(candidates)):
            links = [(a, b, .9 - i / 100) for i, (a, b) in enumerate(candidates) if mask & (1 << i)]
            proven = {tuple(sorted((a, b))) for a, b, _ in links}
            components = coherent_groups('abcd', links)
            covered = set()
            for group in components:
                self.assertTrue(set(itertools.combinations(group, 2)).issubset(proven))
                covered.update(itertools.combinations(group, 2))
            self.assertEqual(covered, proven)
            self.assertEqual(len(components), len({tuple(group) for group in components}))

    def test_can_stop_during_growth_of_dense_graph(self):
        keys = [str(i).zfill(2) for i in range(30)]
        links = [(a, b, .9) for a, b in itertools.combinations(keys, 2)]
        # Sept contrôles pendant l'indexation ; le neuvième intervient pendant la construction.
        verifier = Mock(side_effect=[None] * 8 + [RuntimeError('arrêt')])
        with self.assertRaisesRegex(RuntimeError, 'arrêt'):
            coherent_groups(keys, links, verifier)

    def test_native_evaluator_uses_overlapping_groups_without_indirect_positive(self):
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='', suffix='.csv') as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            for a, b, score, answer in [('a', 'b', .9, 'oui'), ('b', 'c', .85, 'oui'), ('a', 'c', .4, 'non')]:
                writer.writerow({'type_a': 'article', 'id_a': a, 'type_b': 'article', 'id_b': b,
                                 'langues': 'same', 'score': score, 'meme_evenement': answer})
            output.flush()
            with patch('sys.stdout', new_callable=io.StringIO) as printed:
                evaluate(output.name)
            self.assertIn('groupes (scores seuls) seuil=0.76 précision=1.000 rappel=1.000', printed.getvalue())


class RelatedGroupIntegrationTests(unittest.TestCase):
    def test_real_vectors_split_chain_and_keep_see_also_neighbors(self):
        data = [(k, item, f, [math.cos(angle), math.sin(angle)])
                for (k, item, f, _), angle in zip(rows(), (0., .3, .8))]
        sources, groups = calculate(data, {}, lambda *args: False)
        self.assertEqual(members(groups), [('a', 'b'), ('b', 'c')])
        self.assertEqual({n['targetId'] for n in sources[1]['neighbors']}, {'a', 'c'})

    def test_publisher_restriction_cannot_be_bypassed_by_third_source(self):
        _, groups = calculate(rows(publishers={'a': 'same', 'c': 'same'}), {}, lambda *args: False,
                              pairs=[('a', 'b', .95), ('b', 'c', .9), ('a', 'c', .99)])
        self.assertEqual(members(groups), [('a', 'b'), ('b', 'c')])

    def test_window_applies_to_all_members_including_endpoint_pair(self):
        data = rows(dates={'a': '2026-10-16T12:00:00Z', 'b': '2026-10-19T12:00:00Z',
                          'c': '2026-10-22T12:00:00Z'})
        _, groups = calculate(data, {}, lambda *args: False,
                              pairs=[('a', 'b', .95), ('b', 'c', .9), ('a', 'c', .99)])
        self.assertEqual(members(groups), [('a', 'b'), ('b', 'c')])

    def test_judge_rejection_cannot_be_bypassed_and_no_extra_call_is_added(self):
        judge = Mock(side_effect=lambda a, b, *_: {a['id'], b['id']} != {'a', 'c'})
        _, groups = calculate(rows(), {}, judge,
                              pairs=[('a', 'b', .66), ('b', 'c', .65), ('a', 'c', .61)])
        self.assertEqual(members(groups), [('a', 'b'), ('b', 'c')])
        self.assertEqual(judge.call_count, 3)

    def test_judge_can_validate_a_complete_group(self):
        judge = Mock(return_value=True)
        _, groups = calculate(rows(), {}, judge,
                              pairs=[('a', 'b', .66), ('b', 'c', .65), ('a', 'c', .61)])
        self.assertEqual(members(groups), [('a', 'b', 'c')])
        self.assertEqual(judge.call_count, 3)

    def test_missing_common_clue_at_endpoints_prevents_indirect_grouping(self):
        data = rows()
        for (_, item, _, _), title in zip(data, ('News Paris Alpha', 'News Paris London Bravo', 'News London Charlie')):
            item['title'] = title
        judge = Mock(return_value=False)
        _, groups = calculate(data, {}, judge,
                              pairs=[('a', 'b', .95), ('b', 'c', .9), ('a', 'c', .99)])
        self.assertEqual(members(groups), [('a', 'b'), ('b', 'c')])
        judge.assert_called_once()

    def test_below_threshold_endpoint_link_stays_rejected_even_when_present(self):
        _, groups = calculate(rows(), {}, lambda *args: False,
                              pairs=[('a', 'b', .95), ('b', 'c', .9), ('a', 'c', .59)])
        self.assertEqual(members(groups), [('a', 'b'), ('b', 'c')])

    def test_unknown_language_keeps_cross_language_threshold(self):
        data = rows(languages={'a': 'und', 'b': 'und'})[:2]
        _, groups = calculate(data, {}, lambda *args: False, pairs=[('a', 'b', .65)])
        self.assertEqual(members(groups), [('a', 'b')])

    def test_group_identity_members_and_title_stay_stable_with_input_order(self):
        data = rows()
        pairs = [('a', 'b', .9), ('b', 'c', .9), ('a', 'c', .9)]
        for variant in (data, list(reversed(data))):
            for order in itertools.permutations(pairs):
                _, groups = calculate(variant, {}, lambda *args: False, pairs=order)
                self.assertEqual(members(groups), [('a', 'b', 'c')])
                self.assertEqual(groups[0]['title'], 'News Paris A')
                self.assertEqual(groups[0]['groupId'], hashlib.sha256(b'a|b|c').hexdigest()[:32])
                self.assertTrue(groups[0]['dossierCandidate'])

    def test_title_uses_only_links_inside_accepted_group(self):
        data = rows()
        data.append(('d', {**data[0][1], 'id': 'd', 'publisher': 'd'}, 'd', [1., 0.]))
        _, groups = calculate(data, {}, lambda *args: False,
                              pairs=[('a', 'b', .99), ('a', 'c', .96), ('b', 'c', .95), ('b', 'd', .94)])
        self.assertEqual(members(groups), [('a', 'b', 'c'), ('b', 'd')])
        self.assertEqual(groups[0]['title'], 'News Paris A')

    def test_old_transitive_group_is_removed_when_coherent_group_is_published(self):
        _, groups = calculate(rows(), {}, lambda *args: False,
                              pairs=[('a', 'b', .9), ('b', 'c', .8)])
        old_id = hashlib.sha256(b'a|b|c').hexdigest()[:32]
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                store.set('groups', [old_id])
                request = Mock()
                publish(store, {}, request, [], groups, lambda: None)
                published = [call.args[3]['groups'][0] for call in request.call_args_list]
                self.assertEqual(published[-1], {'groupId': old_id, 'members': [], 'title': '',
                                                 'dossierCandidate': False})
                self.assertEqual(store.get('groups'), sorted(g['groupId'] for g in groups))
                request.reset_mock()
                publish(store, {}, request, [], groups, lambda: None)
                request.assert_not_called()
            finally:
                store.close()
