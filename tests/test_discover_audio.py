"""Voix Kokoro : Bella et George au débit naturel, sans calibrage ralenti."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover_audio


class VoixTests(unittest.TestCase):
    def test_bella_pour_la_narration_et_george_pour_le_second_intervenant(self):
        self.assertEqual(discover_audio.VOICES, {'Narrator': 'af_bella', 'Host': 'af_bella', 'Guest': 'bm_george'})

    def test_debit_naturel(self):
        self.assertEqual(discover_audio.vitesses(), {'af_bella': 1.0, 'bm_george': 1.0})


if __name__ == '__main__':
    unittest.main()
