"""Annotations intégrales : couverture, contexte, citations et validation du contrat sans API."""
import copy
import json
import unittest
from unittest.mock import Mock

from discover_annotations import generer_annotations, position_citation
from manifeste_validation import ErreurManifeste, valider_segments


class AnnotationTests(unittest.TestCase):
    def test_position_unicode_et_deuxieme_occurrence(self):
        texte = '🎧 They hold on, then hold on.'
        debut, fin = position_citation(texte, 'hold on', 1)
        self.assertEqual(texte[debut:fin], 'hold on')
        self.assertEqual(debut, texte.rfind('hold on'))
        for citation, occurrence in [('hold out', 0), ('hold on', 2), ('', 0), ('hold', -1)]:
            with self.subTest(citation=citation, occurrence=occurrence), self.assertRaises(ValueError):
                position_citation(texte, citation, occurrence)

    def test_analyse_de_tous_les_blocs_avec_contexte_sans_annotations_forcees(self):
        segments = [{'id': f's{i}', 'text': 'word ' * 200} for i in range(3)]
        prompts = []

        def demander(etape, prompt, schema, valider):
            source = json.loads(prompt.split('<source_data>')[1].split('</source_data>')[0])
            prompts.append(source)
            reponse = {'segments': [{'segmentId': s['id'], 'annotations': []} for s in source['segments']]}
            valider(reponse)
            return reponse

        self.assertEqual(generer_annotations(Mock(demander=demander), segments, 'A2'), [])
        self.assertEqual([p['segments'][0]['id'] for p in prompts], ['s0', 's1', 's2'])
        self.assertEqual([s['id'] for s in prompts[1]['context']], ['s0', 's2'])

    def test_segment_oublie_ou_duplique_refuse(self):
        segments = [{'id': 's1', 'text': 'Hello.'}, {'id': 's2', 'text': 'Bye.'}]
        for ids in (['s1'], ['s1', 's1'], ['s1', 'unknown']):
            def demander(etape, prompt, schema, valider):
                reponse = {'segments': [{'segmentId': i, 'annotations': []} for i in ids]}
                valider(reponse)
                return reponse
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                generer_annotations(Mock(demander=demander), segments, 'A2')

    def test_citation_inventee_et_chevauchement_refuses(self):
        for citations in (['hold out'], ['hold on', 'hold']):
            def demander(etape, prompt, schema, valider):
                reponse = {'segments': [{'segmentId': 's1', 'annotations': [
                    {'text': t, 'occurrence': 0, 'meaning': 'Attendre.', 'note': 'Sens ici.'} for t in citations]}]}
                valider(reponse)
                return reponse
            with self.subTest(citations=citations), self.assertRaises(ValueError):
                generer_annotations(Mock(demander=demander), [{'id': 's1', 'text': 'Please hold on.'}], 'A2')

    def test_contrat_accepte_aide_hors_extrait_et_texte_facile_sans_aide(self):
        variant, doc = document()
        self.assertEqual(valider_segments(doc, variant), doc)
        doc['guide']['annotations'] = []
        self.assertEqual(valider_segments(doc, variant), doc)

    def test_contrat_refuse_mauvaise_position_et_densite_excessive(self):
        variant, doc = document()
        for mutation in ('offset', 'quote', 'overlap', 'density', 'blank', 'unknown'):
            bad = copy.deepcopy(doc)
            notes = bad['guide']['annotations']
            if mutation == 'offset':
                notes[0]['startChar'] += 1
            elif mutation == 'quote':
                notes[0]['text'] = 'fake'
            elif mutation == 'overlap':
                notes.append(dict(notes[0]))
            elif mutation == 'density':
                bad['segments'][1]['text'] = 'a b c d'
                notes[:] = [{**notes[0], 'text': c, 'startChar': i * 2, 'endChar': i * 2 + 1}
                            for i, c in enumerate('abcd')]
            elif mutation == 'blank':
                notes[0]['note'] = ' '
            else:
                notes[0]['segmentId'] = 'unknown'
            with self.subTest(mutation=mutation), self.assertRaises(ErreurManifeste):
                valider_segments(bad, variant)


def document():
    variant = {'key': 'en-source', 'language': 'en', 'audio': {'timingSource': 'rss_vtt', 'durationMs': 3000}}
    texte = '🎧 Please hold on, then hold on.'
    debut, fin = position_citation(texte, 'hold on', 1)
    note = {'segmentId': 's2', 'text': 'hold on', 'meaning': 'Attendre.', 'note': 'On demande de patienter.',
            'startChar': debut, 'endChar': fin}
    doc = {'schemaVersion': 1, 'variantKey': 'en-source', 'segments': [
        {'id': 's1', 'text': 'Hello.', 'startMs': 0, 'endMs': 1000},
        {'id': 's2', 'text': texte, 'startMs': 1000, 'endMs': 3000}],
        'guide': {'level': 'A2', 'voice': 'original', 'passage': {'fromSegment': 's1', 'toSegment': 's1'},
                  'expressions': [], 'listening': [], 'annotations': [note]}}
    return variant, doc
