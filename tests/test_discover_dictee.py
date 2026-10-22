"""Découpage et horodatage des phrases du passage de dictée."""
import unittest

from discover_dictee import unites
from manifeste_validation import valider_dictee


def segment(text, start=0, end=10000, **extra):
    return {'id': 's001', 'text': text, 'startMs': start, 'endMs': end, **extra}


class DicteeTests(unittest.TestCase):
    def test_coupe_sur_virgule_avec_heure_du_mot(self):
        mots = [f'word{i}' + (',' if i == 11 else '') for i in range(30)]
        texte = ' '.join(mots)
        s = segment(texte, end=30000, phrases=[{'text': texte, 'startMs': 0, 'endMs': 30000,
                                               'wordStarts': list(range(0, 30000, 1000))}])
        result = unites([s])
        self.assertEqual([len(u['text'].split()) for u in result], [12, 18])
        self.assertEqual((result[0]['endMs'], result[1]['startMs']), (12000, 12000))
        valider_dictee(result, [s], 0, 0)

    def test_prorata_et_fusion_des_courtes(self):
        s = segment('Yes. We can hear this clearly. Another sentence is spoken here.')
        result = unites([s])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['text'], 'Yes. We can hear this clearly.')
        self.assertEqual(result[0]['startMs'], 0)
        self.assertEqual(result[-1]['endMs'], 10000)
        self.assertEqual(result[0]['endMs'], result[1]['startMs'])
        valider_dictee(result, [s], 0, 0)

    def test_bornes_ordre_et_limite_cent(self):
        segments = [dict(segment('We can hear this clearly.', i * 1000, (i + 1) * 1000), id=f's{i:03d}') for i in range(110)]
        result = unites(segments)
        self.assertEqual(len(result), 100)
        self.assertEqual(result[-1]['id'], 'd100')
        valider_dictee(result, segments, 0, len(segments) - 1)
        s = segment('We can hear this clearly.', start=100, end=900,
                    phrases=[{'text': 'We can hear this clearly.', 'startMs': 0, 'endMs': 1200}])
        self.assertEqual((unites([s])[0]['startMs'], unites([s])[0]['endMs']), (100, 900))
        self.assertEqual(unites([segment('Too short.')]), [])
        self.assertEqual(unites([segment('No timing available.', start=None, end=None)]), [])

    def test_phrases_originales_et_horaires_conserves(self):
        s = segment('We can hear clearly. Then we try again.', phrases=[
            {'text': 'We can hear clearly.', 'startMs': 100, 'endMs': 4000},
            {'text': 'Then we try again.', 'startMs': 5000, 'endMs': 9000}])
        result = unites([s])
        self.assertEqual([(u['startMs'], u['endMs']) for u in result], [(100, 4000), (5000, 9000)])
        valider_dictee(result, [s], 0, 0)
