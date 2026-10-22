"""Original guidé : traductions, passage, guide et publication, avec une IA simulée et sans réseau."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover_guide as guide
import discover_preparation as workflow
from discover_ai import FournisseurIndisponible
from manifeste_validation import valider_manifeste

QUESTIONS = [{'question': f'Question {i}?', 'choices': ['Rates stay the same', 'Rates go up', 'Rates go down'],
              'correctChoice': 0, 'explanation': 'The bank holds rates.', 'segmentIndex': 0} for i in range(3)]


def video(n, pas=30_000):
    """n phrases anglaises horodatées, une toutes les 30 secondes."""
    return [{'id': f's{i:04d}', 'text': f'The Bank of England is expected to hold interest rates steady, part {i}.',
             'startMs': i * pas, 'endMs': (i + 1) * pas - 500} for i in range(n)]


class FauxClient:
    """Répond selon l'étape demandée et applique la validation, comme le client réel."""
    def __init__(self, reponses):
        self.reponses, self.etapes, self.appels = reponses, [], {}

    def demander(self, etape, prompt, schema, valider=lambda _: None, juge=False, cache_schema=None):
        self.etapes.append(etape)
        cle = next(k for k in self.reponses if etape.startswith(k))
        reponse = self.reponses[cle]
        reponse = reponse(prompt) if callable(reponse) else reponse
        if isinstance(reponse, Exception):
            raise reponse
        valider(reponse)
        return reponse

    def statistiques(self):
        return {}


def traductions(prompt, texte=lambda i: 'Traduction ' + i, promotion=lambda i: False):
    ids = json.loads(prompt.split('<source_data>')[1].split('</source_data>')[0])['segments']
    return {'translations': [{'sourceId': s['id'], 'text': texte(s['id']), 'promotion': promotion(s['id'])} for s in ids]}


NOTES = {'expressions': [{'segmentId': 's0004', 'text': 'is expected to', 'meaning': 'devrait', 'note': 'Très fréquent.'},
                         {'segmentId': 's0004', 'text': 'hold interest rates steady', 'meaning': 'maintenir les taux', 'note': 'Bloc à retenir.'},
                         {'segmentId': 's0005', 'text': 'Bank of England', 'meaning': 'Banque d’Angleterre', 'note': 'Nom propre.'}],
         'listening': [{'segmentId': 's0004', 'text': 'expected to', 'note': 'À écouter : « to » souvent réduit.'}]}


class TraductionsTests(unittest.TestCase):
    def test_source_francaise_en_anglais_naturel_sans_publicite(self):
        sources = [{'id': 's0001', 'text': 'La Banque devrait maintenir ses taux.'}, {'id': 's0002', 'text': 'Abonnez-vous à la chaîne !'}]
        client = FauxClient({'guide-en': lambda p: traductions(p, lambda i: 'The bank is set to hold rates.', lambda i: i == 's0002')})
        anglais = guide.traduire_vers_anglais(client, sources)
        self.assertEqual(anglais, [{'id': 's0001', 'text': 'The bank is set to hold rates.', 'fr': 'La Banque devrait maintenir ses taux.',
                                    'speaker': 'Narrator', 'sourceSegments': ['s0001']}])

    def test_chaque_phrase_anglaise_est_traduite_une_fois(self):
        client = FauxClient({'guide-fr': lambda p: {'translations': traductions(p)['translations'][:-1]}})
        with self.assertRaises(ValueError):
            guide.traduire_vers_francais(client, video(3))


class PassageTests(unittest.TestCase):
    def test_source_courte_travaillee_en_entier(self):
        segments = video(8)
        self.assertEqual(guide.choisir_passage(FauxClient({}), segments, 'B1')['fromSegment'], 's0000')

    def test_passage_choisi_par_l_ia_et_controle(self):
        segments = video(40)  # 20 minutes
        client = FauxClient({'guide-passage': {'fromSegment': 's0010', 'toSegment': 's0017', 'reason': 'Explique la décision.'}})
        self.assertEqual(guide.choisir_passage(client, segments, 'B1'),
                         {'fromSegment': 's0010', 'toSegment': 's0017', 'reason': 'Explique la décision.'})

    def test_raison_sans_citation_mais_avec_apostrophe_francaise(self):
        for raison in ('Comprendre « hold rates ».', 'Comprendre "hold rates".',
                       "Comprendre 'rates'.", "Comprendre 'don't'.", 'Comprendre ‘rates’.', 'Comprendre ’rates’.',
                       "Le sujet convient à l'apprenant.", 'Le sujet convient à l’apprenant.'):
            with self.subTest(raison=raison):
                client = FauxClient({'guide-passage': {'fromSegment': 's0010', 'toSegment': 's0017', 'reason': raison}})
                passage = guide.choisir_passage(client, video(40), 'B1')
                if raison.startswith('Comprendre'):
                    self.assertEqual(passage['reason'], 'Passage choisi automatiquement (environ 4 minutes).')
                else:
                    self.assertEqual(passage['reason'], raison)

    def test_passage_trop_long_ou_ia_indisponible_remplace_par_4_minutes(self):
        segments = video(40)
        for reponse in ({'fromSegment': 's0001', 'toSegment': 's0030', 'reason': 'Tout.'}, FournisseurIndisponible('quota')):
            with self.subTest(reponse=type(reponse).__name__):
                passage = guide.choisir_passage(FauxClient({'guide-passage': reponse}), segments, 'B1')
                debut, fin = guide.valider_passage(segments, passage['fromSegment'], passage['toSegment'])
                self.assertLessEqual(segments[fin]['endMs'] - segments[debut]['startMs'], guide.PASSAGE_CIBLE_MS)
                self.assertGreater(debut, 0)  # l'introduction est sautée


class GuideTests(unittest.TestCase):
    def setUp(self):
        self.segments = video(12)
        self.passage = {'fromSegment': 's0004', 'toSegment': 's0007'}

    def test_guide_cite_exactement_le_passage_et_quiz_dans_le_document_complet(self):
        client = FauxClient({'guide-notes': NOTES, 'quiz': {'questions': QUESTIONS}})
        resultat, quiz = guide.generer_guide(client, self.segments, self.passage, 'B1', 'original', {})
        self.assertEqual([n['text'] for n in resultat['expressions']], ['is expected to', 'hold interest rates steady', 'Bank of England'])
        self.assertEqual(resultat['voice'], 'original')
        self.assertEqual({q['segmentIndex'] for q in quiz}, {4})  # position 0 du passage = segment 4 du document

    def test_expression_inventee_refusee(self):
        notes = {**NOTES, 'expressions': [{'segmentId': 's0004', 'text': 'cut rates sharply', 'meaning': 'baisser', 'note': 'x'}]}
        with self.assertRaises(ValueError):
            guide.generer_guide(FauxClient({'guide-notes': notes}), self.segments, self.passage, 'B1', 'original', {})

    def test_aucun_point_d_ecoute_sur_une_voix_de_synthese(self):
        with self.assertRaises(ValueError):
            guide.generer_guide(FauxClient({'guide-notes': NOTES}), self.segments, self.passage, 'B1', 'synthetic', {})


def voix(segments, folder, name, verifier, speeds=None):
    timings = Path(folder) / 'timings.json'
    timings.write_text(json.dumps([{'id': s['id'], 'startMs': i * 2000, 'endMs': i * 2000 + 1500} for i, s in enumerate(segments)]))
    mp3 = Path(folder) / 'en.mp3'
    mp3.write_bytes(b'ID3-voice')
    return {'file': str(mp3), 'timingsFile': str(timings), 'durationMs': len(segments) * 2000,
            'origin': 'deepgram', 'timingSource': 'deepgram'}


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'youtube-dQw4w9WgXcQ'
        self.root.mkdir()
        self.audio = self.root / 'source.mp3'
        self.audio.write_bytes(b'ID3-source')
        self.segments = self.root / 'segments-source.json'
        self.item = {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'ref': 'dQw4w9WgXcQ', 'kind': 'youtube', 'leaseToken': 'token',
                     'source': {'kind': 'youtube', 'title': 'Rates', 'language': 'en', 'category': 'economy',
                                'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'},
                     'options': {'coverage': 'guided', 'level': 'B1', 'style': 'narration', 'targetMinutes': None,
                                 'faithful': False, 'keepOriginalCopy': False}}

    def tearDown(self):
        self.tmp.cleanup()

    def publier(self, segments, client, langue='en', **patches):
        self.segments.write_text(json.dumps({'language': langue, 'timingSource': 'rss_vtt', 'segments': segments}))
        self.item['source']['language'] = langue  # renseignée par la préparation de la source, comme dans la file
        source = {'segmentsFile': str(self.segments), 'audioFile': str(self.audio)}
        publies = []
        with mock.patch('discover_cible.requete', side_effect=workflow.discover_cible.ErreurDiscover(404, 'not_found')), \
                mock.patch('discover_cible.publier_manifeste', side_effect=lambda m, p, **k: publies.append((m, p)) or {'status': 'ready'}), \
                mock.patch('pipeline.duree_audio_secondes', return_value=360), mock.patch('discover_costs.enregistrer'):
            for cible, valeur in patches.items():
                stack = mock.patch(cible, valeur)
                stack.start()
                self.addCleanup(stack.stop)
            workflow.preparer(self.item, source, self.root, lambda _: None, lambda: None, {}, client)
        return publies[0]

    def test_video_anglaise_publie_l_original_avec_francais_guide_et_quiz(self):
        client = FauxClient({'guide-fr': traductions, 'guide-notes': NOTES, 'quiz': {'questions': QUESTIONS}})
        manifest, paths = self.publier(video(9), client)
        valider_manifeste(manifest)
        self.assertEqual([v['kind'] for v in manifest['variants']], ['source'])
        source = manifest['variants'][0]
        self.assertEqual(source['audio']['origin'], 'original')
        self.assertEqual(len(source['quiz']), 3)
        doc = json.loads(Path(paths[source['segmentsFile']]).read_text())
        self.assertEqual(doc['segments'][4]['fr'], 'Traduction s0004')
        self.assertEqual(doc['guide']['passage']['fromSegment'], 's0000')  # 4 min 30 : travaillée en entier
        self.assertNotIn('guide-passage', client.etapes)

    def test_source_francaise_traduite_lue_en_entier_et_guidee(self):
        francais = [{**s, 'text': f'La Banque d’Angleterre devrait maintenir ses taux, partie {i}.'} for i, s in enumerate(video(12))]
        speech = mock.Mock(provider='deepgram')
        speech.generate.side_effect = voix
        notes = {'expressions': NOTES['expressions'], 'listening': []}
        client = FauxClient({'guide-en': lambda p: traductions(p, lambda i: f'The Bank of England is expected to hold interest rates steady, part {int(i[1:])}.'),
                             'guide-notes': notes, 'quiz': {'questions': QUESTIONS}})
        manifest, paths = self.publier(francais, client, 'fr', **{'discover_speech.Session': mock.Mock(return_value=speech)})
        valider_manifeste(manifest)
        self.assertEqual([(v['key'], v['kind']) for v in manifest['variants']], [('fr-source', 'source'), ('en-faithful', 'faithful_translation')])
        anglais = manifest['variants'][1]
        self.assertEqual((anglais['audio']['origin'], len(anglais['quiz'])), ('deepgram', 3))
        doc = json.loads(Path(paths[anglais['segmentsFile']]).read_text())
        self.assertEqual((doc['guide']['voice'], doc['guide']['listening']), ('synthetic', []))
        self.assertTrue(doc['segments'][0]['fr'].startswith('La Banque'))
        self.assertNotIn('guide', json.loads(Path(paths[manifest['variants'][0]['segmentsFile']]).read_text()))

    def test_texte_anglais_lu_tel_quel_par_une_voix(self):
        note = '3f1d9c6e-8b2a-4c7d-9e10-2a3b4c5d6e7f'
        self.item.update(ref=note, kind='reflection', source={'kind': 'reflection', 'title': 'Story', 'language': 'en'})
        texte = [{**s, 'startMs': None, 'endMs': None} for s in video(6)]
        self.segments.write_text(json.dumps({'language': 'en', 'timingSource': 'none', 'segments': texte}))
        speech = mock.Mock(provider='deepgram')
        speech.generate.side_effect = voix
        client = FauxClient({'guide-fr': traductions, 'guide-notes': {'expressions': NOTES['expressions'], 'listening': []},
                             'quiz': {'questions': QUESTIONS}})
        publies = []
        with mock.patch('discover_cible.requete', side_effect=workflow.discover_cible.ErreurDiscover(404, 'not_found')), \
                mock.patch('discover_cible.publier_manifeste', side_effect=lambda m, p, **k: publies.append((m, p)) or {'status': 'ready'}), \
                mock.patch('discover_speech.Session', return_value=speech), mock.patch('discover_costs.enregistrer'):
            workflow.preparer(self.item, {'segmentsFile': str(self.segments), 'audioFile': None}, self.root, lambda _: None, lambda: None, {}, client)
        manifest, paths = publies[0]
        valider_manifeste(manifest)
        lu = manifest['variants'][1]
        self.assertEqual((lu['key'], lu['kind'], lu['cefrLevel'], lu['coverage']), ('en-full-original', 'adaptation', None, 'full'))
        doc = json.loads(Path(paths[lu['segmentsFile']]).read_text())
        self.assertEqual([s['text'] for s in doc['segments']], [s['text'] for s in texte])  # anglais non réécrit
        self.assertEqual((doc['guide']['voice'], doc['segments'][0]['fr']), ('synthetic', 'Traduction s0000'))
        self.assertNotIn('audio', manifest['variants'][0])


if __name__ == '__main__':
    unittest.main()
