"""Lecture d’une décision explicite, sans réseau dans les tests."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import discover_affaire as affaire
from discover_source import SourceRefusee

FIXTURES = Path(__file__).parent / 'fixtures' / 'affaires'


class AffaireTests(unittest.TestCase):
    def test_courtlistener_retire_notes_et_conserve_opinions(self):
        data = json.loads((FIXTURES / 'courtlistener.json').read_text())
        def lire(url, token=None):
            self.assertEqual(token, 'secret-test')
            return json.dumps(data[url.removeprefix(affaire.API)]).encode()
        with patch.object(affaire, '_lire', side_effect=lire) as lecture:
            result = affaire.recuperer_affaire('https://www.courtlistener.com/opinion/42/exemple/',
                                             {'courtlistener_token': 'secret-test'})
        self.assertEqual(lecture.call_count, 5)
        self.assertEqual(result['citation'], '123 U.S. 456')
        self.assertIn('The buyer appealed.', result['text'])
        self.assertIn('Dissent:', result['text'])
        self.assertNotIn('FOOTNOTE', result['text'])
        self.assertNotIn('BAD', result['text'])

    def test_find_case_law_metadonnees_et_suite_apres_notes(self):
        with patch.object(affaire, '_lire', return_value=(FIXTURES / 'find_case_law.xml').read_bytes()) as lecture:
            result = affaire.recuperer_affaire('https://caselaw.nationalarchives.gov.uk/uksc/2024/1')
        lecture.assert_called_once_with('https://caselaw.nationalarchives.gov.uk/uksc/2024/1/data.xml')
        self.assertEqual(result['court'], 'The Supreme Court')
        self.assertEqual(result['citation'], '[2024] UKSC 1')
        self.assertIn('on the evidence. The parties disagree.', result['text'])
        self.assertNotIn('FOOTNOTE', result['text'])
        self.assertIn('Open Justice Licence', result['licence'])

    def test_refuse_sources_recherche_et_parametres(self):
        for url in ('http://www.courtlistener.com/opinion/42/', 'https://example.com/opinion/42/',
                    'https://www.courtlistener.com/?q=case', 'https://caselaw.nationalarchives.gov.uk/search',
                    'https://user@www.courtlistener.com/opinion/42/'):
            with self.subTest(url=url), self.assertRaises(SourceRefusee):
                affaire.recuperer_affaire(url)

    def test_jeton_requis_avant_tout_appel(self):
        with patch.object(affaire, '_lire') as lecture, self.assertRaises(ValueError):
            affaire.recuperer_affaire('https://www.courtlistener.com/opinion/42/', {})
        lecture.assert_not_called()

    def test_refuse_entites_xml(self):
        with patch.object(affaire, '_lire', return_value=b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///tmp/x">]>'):
            with self.assertRaisesRegex(ValueError, 'XML externes'):
                affaire.recuperer_affaire('https://caselaw.nationalarchives.gov.uk/uksc/2024/1')

    def test_refuse_lien_api_externe(self):
        with patch.object(affaire, '_lire') as lecture, self.assertRaises(ValueError):
            affaire._api('https://example.com/opinions/1/', 'opinions', 'secret-test')
        lecture.assert_not_called()
