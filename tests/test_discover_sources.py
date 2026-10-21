import json
import tempfile
import unittest
from pathlib import Path

import discover_podcast_bundle as bundle
import discover_source


class TexteTests(unittest.TestCase):
    def test_decoupe_sans_couper_les_phrases_ni_fusionner_les_paragraphes(self):
        texte = '# Titre\n\n' + ' '.join(f'Phrase numéro {i} assez longue pour remplir.' for i in range(12)) + '\n\nDernier paragraphe.'
        segments = discover_source.decouper_texte(texte, cible=120)
        self.assertEqual(segments[0], 'Titre')
        self.assertEqual(segments[-1], 'Dernier paragraphe.')
        self.assertTrue(all(s.endswith('.') or s == 'Titre' for s in segments))
        self.assertTrue(all(len(s) < 200 for s in segments))

    def test_detecte_francais_et_anglais(self):
        self.assertEqual(discover_source.detecter_langue('La dette est un sujet que les économistes suivent de près.'), 'fr')
        self.assertEqual(discover_source.detecter_langue('The debt is a topic that economists follow closely, and it is growing.'), 'en')


class PisteSousTitresTests(unittest.TestCase):
    def test_manuels_d_abord(self):
        info = {'subtitles': {'en': [], 'de': []}, 'automatic_captions': {'en-orig': [], 'en': []}}
        self.assertEqual(discover_source.piste_sous_titres(info, 'en'), ('en', False))

    def test_automatique_d_origine_et_pas_une_traduction(self):
        # Vidéo française : « en » est une traduction machine, « fr-orig » la reconnaissance d'origine.
        info = {'subtitles': {}, 'automatic_captions': {'en': [], 'fr': [], 'fr-orig': [], 'de': []}}
        self.assertEqual(discover_source.piste_sous_titres(info, None), ('fr-orig', True))
        self.assertEqual(discover_source.piste_sous_titres(info, 'fr'), ('fr-orig', True))

    def test_langue_de_la_video_sans_piste_orig(self):
        info = {'automatic_captions': {'en': [], 'fr': []}}
        self.assertEqual(discover_source.piste_sous_titres(info, 'en'), ('en', True))
        self.assertEqual(discover_source.piste_sous_titres(info, None), (None, None))

    def test_aucun_sous_titre(self):
        self.assertEqual(discover_source.piste_sous_titres({'subtitles': {'live_chat': []}}, 'en'), (None, None))


class ManifesteTests(unittest.TestCase):
    def test_identifiants_selon_la_source(self):
        with self.assertRaises(ValueError):
            bundle.content_id({'ref': 'a' * 20, 'source': {'kind': 'episode'}})
        youtube = bundle.content_id({'ref': 'dQw4w9WgXcQ', 'source': {'kind': 'youtube'}})
        self.assertRegex(youtube, r'^youtube-[0-9a-f]{20}$')
        note = '3f1d9c6e-8b2a-4c7d-9e10-2a3b4c5d6e7f'
        self.assertEqual(bundle.content_id({'ref': note, 'source': {'kind': 'reflection'}}), 'reflection-' + note)

    def test_note_sans_audio_source_publie_une_adaptation_narree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            segments = tmp / 'segments-source.json'
            segments.write_text(json.dumps({'language': 'fr', 'timingSource': 'none', 'segments': [
                {'id': 's0001', 'text': 'Une idée sur la dette.', 'startMs': None, 'endMs': None}]}))
            timings = tmp / 'timings.json'
            timings.write_text(json.dumps([{'id': 'p0001', 'startMs': 0, 'endMs': 1500}]))
            audio = tmp / 'en.mp3'
            audio.write_bytes(b'ID3fake')
            note = '3f1d9c6e-8b2a-4c7d-9e10-2a3b4c5d6e7f'
            item = {'id': '11111111-1111-4111-8111-111111111111', 'ref': note,
                    'source': {'kind': 'reflection', 'id': note, 'title': 'Dette', 'language': 'fr', 'category': None},
                    'options': {'coverage': 'full', 'level': 'B1', 'style': 'narration', 'targetMinutes': None, 'faithful': False, 'keepOriginalCopy': False}}
            prepared = {'script': {'segments': [{'id': 'p0001', 'text': 'An idea about debt.', 'fr': 'Une idée sur la dette.', 'speaker': 'Narrator', 'sourceSegments': ['s0001']}], 'keyVocab': []},
                        'generation': {}, 'evaluation': {'verdict': 'ok'}}
            manifest, paths = bundle.construire(item, {'segmentsFile': str(segments), 'audioFile': None}, prepared,
                                                {'timingsFile': str(timings), 'file': str(audio), 'durationMs': 1500}, tmp / 'pub')
        self.assertEqual(manifest['content'], {'id': 'reflection-' + note, 'title': 'Dette', 'originalLanguage': 'fr', 'rights': 'personal_use',
                                               'category': None, 'editorial': 'discovery', 'sourceType': 'reflection',
                                               'sourceRef': 'reflection:' + note, 'sourceUrl': None})
        source = next(v for v in manifest['variants'] if v['kind'] == 'source')
        self.assertNotIn('audio', source)
        adapted = next(v for v in manifest['variants'] if v['kind'] == 'adaptation')
        self.assertEqual(adapted['audio']['origin'], 'kokoro')


if __name__ == '__main__':
    unittest.main()
