"""La couverture des faits et l’audit indépendant sont obligatoires."""
import copy
import unittest
from unittest.mock import Mock

import discover_histoire as histoire


def exemple():
    phrase = 'The buyer asked the seller to explain the contract before signing it.'
    texte = ' '.join([phrase] * 50)
    return {'text': phrase}, {'title': 'A disputed contract',
        'story_paragraphs': [{'speaker': 'Narrator', 'text': texte}],
        'question': 'What should the court decide?', 'choices': ['Allow the appeal', 'Dismiss the appeal'],
        'verdict': 0, 'verdict_explanation_fr': 'La cour accueille le recours.',
        'facts_check': [{'fact': phrase, 'source_sentence': phrase}]}


class HistoireTests(unittest.TestCase):
    def test_histoire_valide_et_voix(self):
        source, obj = exemple()
        histoire.valider_histoire(obj, source, 'B1')
        self.assertEqual(histoire.VOIX, {'Narrator': 'af_bella', 'Guest': 'bm_george'})

    def test_refuse_citation_inventee_fait_non_couvert_et_verdict_hors_choix(self):
        source, obj = exemple()
        for modifier in (
            lambda x: x['facts_check'][0].update(source_sentence='Invented quote.'),
            lambda x: x['story_paragraphs'][0].update(text=x['story_paragraphs'][0]['text'] + ' Invented fact.'),
            lambda x: x.update(verdict=2),
            lambda x: x.update(choices=['Same', 'same']),
            lambda x: x['story_paragraphs'][0].update(text='Too short.'),
        ):
            candidate = copy.deepcopy(obj)
            modifier(candidate)
            with self.assertRaises(ValueError):
                histoire.valider_histoire(candidate, source, 'B1')

    def test_audit_refuse_citation_sans_appui_semantique(self):
        source, obj = exemple()
        client = Mock()
        rapport = {k: True for k in ('no_invented_facts', 'no_spoiler', 'private_people_anonymised',
                                    'correct_verdict', 'appropriate_language')}
        rapport.update(checks=[{'fact_index': 0, 'supported': False, 'reason': 'Non étayé'}], reason='Refus')
        client.demander.return_value = rapport
        with self.assertRaisesRegex(ValueError, 'Non étayé'):
            histoire._auditer(client, obj, source, 'B1')
        rapport['checks'] = []
        with self.assertRaisesRegex(ValueError, 'chaque fait'):
            histoire._auditer(client, obj, source, 'B1')

    def test_generation_declenche_validation_et_audit(self):
        source, obj = exemple()
        client = Mock()
        rapport = {k: True for k in ('no_invented_facts', 'no_spoiler', 'private_people_anonymised',
                                    'correct_verdict', 'appropriate_language')}
        rapport.update(checks=[{'fact_index': 0, 'supported': True, 'reason': 'Étayé'}], reason='Valide')
        def demander(kind, prompt, schema, valider=None, **kwargs):
            if kind == 'histoire-audit':
                self.assertTrue(kwargs['juge'])
                return rapport
            valider(obj)
            return obj
        client.demander.side_effect = demander
        self.assertEqual(histoire.generer_histoire(client, source, 'B1', {}), obj)
        self.assertEqual(client.demander.call_count, 2)
