import copy
import tempfile
import unittest
from unittest.mock import patch

from discover_citations import nettoyer_segments, nettoyer_texte
import discover_speech


class CitationTests(unittest.TestCase):
    def test_long_citation_list_and_french_are_cleaned_without_losing_links(self):
        refs = [f's{i:04d}' for i in range(70, 94)]
        citation = '(' + ', '.join(refs) + ')'
        segments = [{'id': 'p0001', 'text': 'An explanation. ' + citation,
                     'fr': 'Une explication ' + citation + '.', 'sourceSegments': refs,
                     'speaker': 'Narrator'}]
        original = copy.deepcopy(segments)
        cleaned = nettoyer_segments(segments)
        self.assertEqual(cleaned[0]['text'], 'An explanation.')
        self.assertEqual(cleaned[0]['fr'], 'Une explication.')
        self.assertEqual(cleaned[0]['sourceSegments'], refs)
        self.assertEqual(segments, original)
        self.assertEqual(nettoyer_segments(cleaned), cleaned)

    def test_dossier_and_inline_citations(self):
        self.assertEqual(nettoyer_texte('First [d1-s0070; d2-s0071]. Next (d1-s0070).',
                                      {'d1-s0070', 'd2-s0071'}), 'First. Next.')

    def test_real_parentheses_numbers_and_unknown_ids_are_preserved(self):
        text = 'Growth (2026, 2027), (about 3%), (s0070 is a code), [s9999].'
        self.assertEqual(nettoyer_texte(text, {'s0070'}), text)
        self.assertEqual(nettoyer_texte('Text (s0070, s9999).', {'s0070'}), 'Text (s0070, s9999).')

    def test_reference_only_paragraph_is_rejected(self):
        with self.assertRaises(ValueError):
            nettoyer_segments([{'text': '(s0070)', 'sourceSegments': ['s0070']}])

    def test_both_engines_receive_clean_text_and_estimate_matches(self):
        segments = [{'text': 'A fact. (s0070)', 'fr': 'Un fait. (s0070)',
                     'speaker': 'Narrator', 'sourceSegments': ['s0070']}]
        clean = nettoyer_segments(segments)
        with tempfile.TemporaryDirectory() as folder:
            with patch('discover_speech.discover_deepgram.plan', return_value=[]) as plan:
                session = discover_speech.Session([segments], folder, {'tts': {'provider': 'kokoro'}}, folder)
                self.assertEqual(plan.call_args.args[0], clean)
            with patch('discover_speech.discover_audio.executer', return_value={}) as generate:
                session.generate(segments, folder, 'test', lambda: None, {'af_heart': 1})
                self.assertEqual(generate.call_args.args[0], clean)
            session.provider = 'deepgram'
            with patch.object(session, 'deepgram', return_value={}) as generate:
                session.generate(segments, folder, 'test', lambda: None)
                self.assertEqual(generate.call_args.args[0], clean)


if __name__ == '__main__':
    unittest.main()
