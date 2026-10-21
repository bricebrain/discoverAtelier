"""Contrat des podcasts préparés et du cache audio, sans API ni modèle réel."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover_audio
import discover_podcast_bundle as bundle
from discover_download import empreinte


class PreparedBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        audio = self.root / 'original.mp3'
        audio.write_bytes(b'original-audio')
        doc = self.root / 'source.json'
        doc.write_text(json.dumps({'language': 'fr', 'timingSource': 'macwhisper_srt', 'segments': [{'id': 's001', 'text': 'Une information.', 'startMs': 0, 'endMs': 1000}]}))
        self.source = {'audioFile': str(audio), 'segmentsFile': str(doc)}
        self.options = {'coverage': 'full', 'level': 'B1', 'style': 'narration', 'targetMinutes': None, 'faithful': True, 'keepOriginalCopy': False}
        self.item = {'ref': 'a' * 20, 'source': {'title': 'Titre', 'language': 'fr', 'category': 'economy', 'audioUrl': 'https://example.com/a.mp3'}, 'options': self.options}
        self.prepared = {'script': {'segments': [{'id': 'p001', 'text': 'A fact.', 'fr': 'Une information.', 'sourceSegments': ['s001'], 'speaker': 'Narrator'}], 'keyVocab': ['fact']},
                         'evaluation': {'verdict': 'ok'}, 'generation': {'provider': 'gemini'}}
        mp3 = self.root / 'prepared.mp3'
        mp3.write_bytes(b'prepared-audio')
        timing = self.root / 'timings.json'
        timing.write_text(json.dumps([{'id': 'p001', 'startMs': 0, 'endMs': 1000}]))
        self.audio = {'file': str(mp3), 'timingsFile': str(timing), 'durationMs': 2000}
        self.patch = mock.patch('pipeline.duree_audio_secondes', return_value=2.0)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_original_stays_streamed_and_prepared_timing_is_kokoro(self):
        manifest, paths = bundle.construire(self.item, self.source, self.prepared, self.audio, self.root / 'pub')
        self.assertEqual(manifest['variants'][0]['audio']['source'], 'publisher_stream')
        self.assertEqual(manifest['variants'][1]['audio']['timingSource'], 'kokoro')
        self.assertEqual(manifest['content']['sourceRef'], 'episode:' + self.item['ref'])
        self.assertFalse(any('fr-source.mp3' in path for path in paths))

    def test_another_version_keeps_existing_variants_and_original_copy(self):
        self.options['keepOriginalCopy'] = True
        first, _ = bundle.construire(self.item, self.source, self.prepared, self.audio, self.root / 'first')
        self.options['keepOriginalCopy'] = False
        self.options.update(coverage='condensed', targetMinutes=12)
        second, _ = bundle.construire(self.item, self.source, self.prepared, self.audio, self.root / 'second', previous=first)
        self.assertEqual({v['key'] for v in second['variants']}, {'fr-source', 'en-full-b1', 'en-condensed-b1-12m'})
        self.assertEqual(second['variants'][0]['audio']['source'], 'r2')

    def test_source_changes_cannot_reinterpret_old_citations(self):
        first, _ = bundle.construire(self.item, self.source, self.prepared, self.audio, self.root / 'first')
        path = Path(self.source['segmentsFile'])
        doc = json.loads(path.read_text()); doc['segments'][0]['text'] = 'Une autre information.'; path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            bundle.construire(self.item, self.source, self.prepared, self.audio, self.root / 'second', previous=first)

    def test_rss_ads_mismatch_cannot_enable_false_synchronisation(self):
        path = Path(self.source['segmentsFile'])
        doc = json.loads(path.read_text()); doc['timingSource'] = 'rss_srt'
        path.write_text(json.dumps(doc))
        with mock.patch('pipeline.duree_audio_secondes', return_value=30):
            manifest, paths = bundle.construire(self.item, self.source, self.prepared, self.audio, self.root / 'rss')
        source_variant = manifest['variants'][0]
        self.assertEqual(source_variant['audio']['timingSource'], 'none')
        segment_doc = json.loads(Path(paths[source_variant['segmentsFile']]).read_text())
        self.assertIsNone(segment_doc['segments'][0]['startMs'])

    def test_youtube_subtitles_keep_timing_despite_music_at_the_end(self):
        path = Path(self.source['segmentsFile'])
        doc = json.loads(path.read_text()); doc['timingSource'] = 'rss_vtt'
        path.write_text(json.dumps(doc))
        self.item.update(ref='dQw4w9WgXcQ', source={**self.item['source'], 'kind': 'youtube', 'audioUrl': None,
                                                                   'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'})
        with mock.patch('pipeline.duree_audio_secondes', return_value=30):
            manifest, _ = bundle.construire(self.item, self.source, self.prepared, self.audio, self.root / 'yt')
        self.assertEqual(manifest['variants'][0]['audio']['timingSource'], 'rss_vtt')

    def test_target_duration_and_dialogue_have_distinct_keys(self):
        self.options.update(coverage='condensed', targetMinutes=12)
        a = bundle.variant_key(self.options)
        self.options['targetMinutes'] = 8
        b = bundle.variant_key(self.options)
        self.options['style'] = 'dialogue'
        self.assertEqual(len({a, b, bundle.variant_key(self.options)}), 3)
