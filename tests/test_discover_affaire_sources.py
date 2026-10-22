"""Seules les sources explicites du catalogue sont acceptées."""
import unittest
from unittest.mock import patch
from discover_affaire_sources import catalogue, extraire
from discover_affaire import _html, normaliser_url_affaire, recuperer_affaire


class CatalogueTests(unittest.TestCase):
    def test_trois_sources_precises_sans_exploration(self):
        for source in catalogue():
            self.assertEqual(normaliser_url_affaire(source['url']), source['url'])
            with patch('discover_affaire._lire', return_value=b'page') as lire, \
                 patch('discover_affaire_sources.extraire', return_value='Verified case facts.'):
                result = recuperer_affaire(source['url'])
            lire.assert_called_once_with(source['url'])
            self.assertEqual(result['nature'], source['nature'])
            self.assertTrue(result['licence'])

    def test_structure_modifiee_refusee(self):
        for source in catalogue():
            with self.assertRaises(ValueError):
                extraire(source, '<html><p>Page vide.</p></html>', _html)
