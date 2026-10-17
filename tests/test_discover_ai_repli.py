import tempfile
import unittest
from unittest import mock

import discover_ai

SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}
CONFIG = {'key': 'gemini-key-123', 'model': 'gemini-test', 'judgeModel': 'gemini-test',
          'openaiKey': 'openai-key-123', 'openaiModel': 'gpt-test', 'openaiJudgeModel': 'gpt-test'}
REPONSE = {'data': {'ok': True}, 'inputTokens': 10, 'outputTokens': 5}


class RepliOpenAI(unittest.TestCase):
    def setUp(self):
        discover_ai.REPLI.update(jusqua=0.0, raison='')
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        discover_ai.REPLI.update(jusqua=0.0, raison='')
        self.tmp.cleanup()

    def client(self, gemini, openai, config=CONFIG):
        return discover_ai.Client(self.tmp.name, config=dict(config), transport=gemini, transport_openai=openai)

    def test_quota_gemini_bascule_sur_openai_puis_reste_sur_openai(self):
        gemini = mock.Mock(side_effect=discover_ai.QuotaAtteint('Quota Gemini atteint.'))
        openai = mock.Mock(return_value=REPONSE)
        client = self.client(gemini, openai)
        self.assertEqual(client.demander('adapt', 'prompt 1', SCHEMA), {'ok': True})
        self.assertEqual(gemini.call_count, 1)
        self.assertEqual(openai.call_args.args[2], 'gpt-test')
        self.assertIn('OpenAI remplace Gemini', discover_ai.etat_repli())
        # Pendant le repli, OpenAI passe en premier : Gemini n'est plus sollicité.
        client.demander('adapt', 'prompt 2', SCHEMA)
        self.assertEqual(gemini.call_count, 1)
        self.assertEqual(client.statistiques()['provider'], 'openai')

    def test_panne_ou_blocage_gemini_bascule_aussi(self):
        for erreur in (discover_ai.FournisseurIndisponible('Gemini indisponible (HTTP 503).'),
                       discover_ai.FournisseurIndisponible('Gemini a bloqué la réponse (SAFETY).')):
            discover_ai.REPLI.update(jusqua=0.0)
            openai = mock.Mock(return_value=REPONSE)
            self.assertEqual(self.client(mock.Mock(side_effect=erreur), openai).demander('juge', 'p ' + str(erreur), SCHEMA, juge=True), {'ok': True})
            openai.assert_called_once()

    def test_les_deux_au_quota_remonte_quota_atteint(self):
        client = self.client(mock.Mock(side_effect=discover_ai.QuotaAtteint('Quota Gemini atteint.')),
                             mock.Mock(side_effect=discover_ai.QuotaAtteint('Quota OpenAI atteint.')))
        with self.assertRaises(discover_ai.QuotaAtteint) as ctx:
            client.demander('adapt', 'prompt', SCHEMA)
        self.assertIn('Gemini', str(ctx.exception))
        self.assertIn('OpenAI', str(ctx.exception))

    def test_sans_cle_openai_le_comportement_reste_celui_de_gemini(self):
        gemini = mock.Mock(side_effect=discover_ai.QuotaAtteint('Quota Gemini atteint.'))
        config = {k: v for k, v in CONFIG.items() if not k.startswith('openai')}
        with self.assertRaises(discover_ai.QuotaAtteint):
            self.client(gemini, mock.Mock(), config).demander('adapt', 'prompt', SCHEMA)
        self.assertIsNone(discover_ai.etat_repli())

    def test_reponse_json_invalide_ne_declenche_pas_le_repli(self):
        gemini = mock.Mock(side_effect=[{'data': {}}, REPONSE])
        openai = mock.Mock()
        self.assertEqual(self.client(gemini, openai).demander('adapt', 'prompt', SCHEMA), {'ok': True})
        openai.assert_not_called()

    def test_le_cache_sert_quel_que_soit_le_fournisseur(self):
        openai = mock.Mock(return_value=REPONSE)
        self.client(mock.Mock(side_effect=discover_ai.QuotaAtteint('q')), openai).demander('adapt', 'prompt', SCHEMA)
        discover_ai.REPLI.update(jusqua=0.0)  # Gemini redevient prioritaire
        gemini = mock.Mock()
        self.assertEqual(self.client(gemini, mock.Mock()).demander('adapt', 'prompt', SCHEMA), {'ok': True})
        gemini.assert_not_called()

    def test_configuration_openai_seule_suffit(self):
        with mock.patch.object(discover_ai, 'CONFIG') as cfg, mock.patch('pathlib.Path.read_text', return_value='{}'), \
                mock.patch('pathlib.Path.exists', return_value=False), mock.patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-test-1234567890', 'GEMINI_API_KEY': ''}):
            cfg.exists.return_value = False
            c = discover_ai.configuration()
        self.assertIsNone(c['key'])
        self.assertEqual(c['openaiKey'], 'sk-test-1234567890')
        self.assertEqual(c['openaiModel'], 'gpt-5-mini')


if __name__ == '__main__':
    unittest.main()
