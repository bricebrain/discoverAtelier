# -*- coding: utf-8 -*-

import http.client
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bundles
import vocabulaire_ia_clients
import vocabulaire_ia_config
import vocabulaire_automatisation
import vocabulaire_lots
import vocabulaire_stockage
import vocabulaire_publication
from vocabulaire_ia_schema import SCHEMA_LOT, schema_pour_gemini
from tests.test_vocabulaire import MOTS, reponse


class TestConfigurationIa(unittest.TestCase):
    def test_reglages_economiques_sans_configuration_locale(self):
        with tempfile.TemporaryDirectory() as dossier, \
                mock.patch.object(vocabulaire_ia_config, "CHEMIN", Path(dossier) / "absent.json"), \
                mock.patch.dict(os.environ, {}, clear=True):
            config = vocabulaire_ia_config.charger()
        self.assertEqual(config["generatorModel"], "gemini-3.1-flash-lite")
        self.assertEqual(config["auditorModel"], "gpt-6-luna")
        self.assertEqual(config["batchSize"], 20)

    def test_les_cles_ne_sont_jamais_retournees(self):
        config = {
            **vocabulaire_ia_config.DEFAUTS,
            "openaiApiKey": "secret-openai", "geminiApiKey": "secret-gemini",
        }
        etat = vocabulaire_ia_config.etat(config)
        self.assertTrue(etat["openaiConfigured"])
        self.assertTrue(etat["geminiConfigured"])
        self.assertNotIn("openaiApiKey", etat)
        self.assertNotIn("geminiApiKey", etat)

    def test_enregistrement_local_et_conservation_des_cles(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "config_ia.json"
            with mock.patch.object(vocabulaire_ia_config, "CHEMIN", chemin), \
                    mock.patch.dict(os.environ, {}, clear=True):
                vocabulaire_ia_config.enregistrer({
                    "openaiApiKey": "oa", "geminiApiKey": "ge",
                    "generatorModel": "gemini-test", "auditorModel": "openai-test",
                    "batchSize": 8, "maxRetries": 3, "autoPublish": True,
                })
                vocabulaire_ia_config.enregistrer({
                    "openaiApiKey": "", "geminiApiKey": "",
                    "generatorModel": "gemini-test", "auditorModel": "openai-test",
                    "batchSize": 8, "maxRetries": 3, "autoPublish": True,
                })
                chargee = vocabulaire_ia_config.charger()
                self.assertEqual(chargee["openaiApiKey"], "oa")
                self.assertEqual(chargee["geminiApiKey"], "ge")


class TestClientsIa(unittest.TestCase):
    def test_erreurs_transport_ouverture_et_lecture_sont_reessayables(self):
        erreurs = [ConnectionResetError(54, "Connection reset by peer"),
                   TimeoutError("timed out"), http.client.RemoteDisconnected("closed"),
                   http.client.IncompleteRead(b"{", 10)]
        for erreur in erreurs:
            for pendant_lecture in (False, True):
                with self.subTest(erreur=type(erreur).__name__, lecture=pendant_lecture):
                    with mock.patch.object(vocabulaire_ia_clients.urllib.request, "urlopen") as ouvrir:
                        if pendant_lecture:
                            ouvrir.return_value.__enter__.return_value.read.side_effect = erreur
                        else:
                            ouvrir.side_effect = erreur
                        with self.assertRaisesRegex(RuntimeError, "Connexion API interrompue"):
                            vocabulaire_ia_clients._poster("https://example.test", {}, {})

    def test_coupure_worker_est_convertie_en_erreur_de_publication(self):
        with mock.patch.object(bundles.urllib.request, "urlopen",
                               side_effect=ConnectionResetError(54, "Connection reset by peer")):
            with self.assertRaisesRegex(RuntimeError, "connexion au Worker interrompue"):
                bundles._requete_worker("https://worker.test/publish", donnees=b"{}", methode="POST")

    def test_controle_openai_en_raisonnement_faible(self):
        reponse_api = {"output_text": "{}", "usage": {
            "input_tokens": 100, "output_tokens": 60,
            "output_tokens_details": {"reasoning_tokens": 20},
        }}
        with mock.patch.object(vocabulaire_ia_clients, "_poster", return_value=reponse_api) as poster:
            resultat = vocabulaire_ia_clients.generer_openai("audit", "gpt-6-luna", "cle-test", SCHEMA_LOT)
        payload = poster.call_args.args[1]
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(resultat["outputTokens"], 60)

    def test_generation_flash_lite_et_comptage_du_raisonnement(self):
        reponse_api = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                       "usageMetadata": {"promptTokenCount": 80,
                                         "candidatesTokenCount": 40,
                                         "thoughtsTokenCount": 10}}
        with mock.patch.object(vocabulaire_ia_clients, "_poster", return_value=reponse_api) as poster:
            resultat = vocabulaire_ia_clients.generer_gemini(
                "generation", "gemini-3.1-flash-lite", "cle-test", SCHEMA_LOT)
        self.assertIn("/models/gemini-3.1-flash-lite:generateContent", poster.call_args.args[0])
        self.assertEqual(poster.call_args.args[1]["generationConfig"]["responseJsonSchema"],
                         schema_pour_gemini(SCHEMA_LOT))
        self.assertEqual(resultat["inputTokens"], 80)
        self.assertEqual(resultat["outputTokens"], 50)

    def test_extrait_texte_openai(self):
        objet = {"output": [{"content": [{"type": "output_text", "text": "{\"ok\":true}"}]}]}
        self.assertEqual(vocabulaire_ia_clients._texte_openai(objet), '{"ok":true}')

    def test_extrait_texte_gemini(self):
        objet = {"candidates": [{"content": {"parts": [{"text": "{\"ok\":true}"}]}}]}
        self.assertEqual(vocabulaire_ia_clients._texte_gemini(objet), '{"ok":true}')

    def test_schema_strict_et_statuts_fermes(self):
        self.assertFalse(SCHEMA_LOT["additionalProperties"])
        entree = SCHEMA_LOT["properties"]["entries"]["items"]
        self.assertFalse(entree["additionalProperties"])
        statuts = entree["properties"]["translationStatus"]["enum"]
        self.assertIn("ambiguous", statuts)
        json.dumps(SCHEMA_LOT)

    def test_schema_gemini_sans_bornes_imbriquees_et_original_intact(self):
        original = json.dumps(SCHEMA_LOT)
        adapte = schema_pour_gemini(SCHEMA_LOT)
        self.assertNotIn('"minItems"', json.dumps(adapte))
        self.assertNotIn('"maxItems"', json.dumps(adapte))
        self.assertEqual(json.dumps(SCHEMA_LOT), original)
        entree = adapte["properties"]["entries"]["items"]
        self.assertFalse(entree["additionalProperties"])
        self.assertEqual(entree["required"], SCHEMA_LOT["properties"]["entries"]["items"]["required"])
        self.assertIn("ambiguous", entree["properties"]["translationStatus"]["enum"])
        self.assertEqual(entree["properties"]["reviewNote"]["type"], ["string", "null"])

    def test_erreur_identifie_le_fournisseur_et_le_modele(self):
        with mock.patch.object(vocabulaire_ia_clients, "_poster",
                               side_effect=RuntimeError("API HTTP 400 : INVALID_ARGUMENT")):
            with self.assertRaisesRegex(RuntimeError, "gemini .*gemini-3.1-flash-lite.*HTTP 400"):
                vocabulaire_ia_clients.generer("gemini", "test", "gemini-3.1-flash-lite", "cle", SCHEMA_LOT)


class TestMigrationAutomatique(unittest.TestCase):
    def test_coupure_api_relance_sans_abandonner_le_lot(self):
        migration = vocabulaire_automatisation.MigrationVocabulaire()
        with mock.patch.object(vocabulaire_ia_clients.urllib.request, "urlopen") as ouvrir, \
                mock.patch.object(vocabulaire_automatisation.time, "sleep"):
            reponse_api = mock.MagicMock()
            reponse_api.__enter__.return_value.read.return_value = json.dumps({
                "output_text": "{}", "usage": {"input_tokens": 12, "output_tokens": 24},
            }).encode()
            ouvrir.side_effect = [ConnectionResetError(54, "Connection reset by peer"), reponse_api]
            resultat = migration._appel_avec_reprises(
                "openai", "gpt-6-luna", "cle-test", "audit", {"maxRetries": 2})
        self.assertEqual(ouvrir.call_count, 2)
        self.assertEqual(resultat["text"], "{}")
        self.assertEqual(migration._etat["usage"]["calls"], 1)

    def test_coupures_persistantes_finissent_par_arreter_les_reprises(self):
        migration = vocabulaire_automatisation.MigrationVocabulaire()
        with mock.patch.object(vocabulaire_ia_clients.urllib.request, "urlopen",
                               side_effect=ConnectionResetError(54, "Connection reset by peer")) as ouvrir, \
                mock.patch.object(vocabulaire_automatisation.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "openai .*Connexion API interrompue"):
                migration._appel_avec_reprises(
                    "openai", "gpt-6-luna", "cle-test", "audit", {"maxRetries": 2})
        self.assertEqual(ouvrir.call_count, 3)

    def test_perimetre_par_defaut_exclut_connus_et_deja_traites(self):
        mots = [{"id": "connu"}, {"id": "publie"}, {"id": "en-cours"}, {"id": "a-traiter"}]
        migration = vocabulaire_automatisation.MigrationVocabulaire()
        config = {**vocabulaire_ia_config.DEFAUTS, "openaiApiKey": "oa", "geminiApiKey": "ge"}
        with mock.patch.object(vocabulaire_automatisation.vocabulaire, "charger_mots", return_value=mots), \
                mock.patch.object(vocabulaire_automatisation.vocabulaire_progression,
                                  "charger_ids_connus", return_value={"connu"}), \
                mock.patch.object(vocabulaire_lots, "statuts_par_mot", return_value={
                    "publie": {"status": "published"}, "en-cours": {"status": "review_required"}}), \
                mock.patch.object(vocabulaire_ia_config, "charger", return_value=config), \
                mock.patch.object(migration, "_executer") as executer:
            migration.demarrer()
            migration._thread.join(timeout=3)
        self.assertEqual(executer.call_args.args[0], ["a-traiter"])
        self.assertEqual(migration._etat["total"], 1)

    def test_corpus_decoupe_en_lots_de_20_sans_perte(self):
        migration = vocabulaire_automatisation.MigrationVocabulaire()
        ids = [f"mot-{index}" for index in range(41)]
        config = dict(vocabulaire_ia_config.DEFAUTS)
        with mock.patch.object(migration, "_traiter_lot",
                               side_effect=lambda bloc, config: len(bloc)) as traiter:
            migration._executer(ids, config)
        blocs = [appel.args[0] for appel in traiter.call_args_list]
        self.assertEqual([len(bloc) for bloc in blocs], [20, 20, 1])
        self.assertEqual([identifiant for bloc in blocs for identifiant in bloc], ids)
        self.assertEqual(migration._etat["processed"], 41)
        self.assertEqual(migration._etat["published"], 41)
        self.assertEqual(migration._etat["status"], "completed")

    def test_generation_audit_approbation_et_publication_sans_revue(self):
        with tempfile.TemporaryDirectory() as dossier:
            ancien_dossier, ancien_chemin = vocabulaire_stockage.DOSSIER, vocabulaire_stockage.CHEMIN
            vocabulaire_stockage.DOSSIER = dossier
            vocabulaire_stockage.CHEMIN = os.path.join(dossier, "revisions.json")
            config = {
                "openaiApiKey": "oa", "geminiApiKey": "ge",
                "generatorModel": "gemini-test", "auditorModel": "openai-test",
                "batchSize": 1, "maxRetries": 1, "autoPublish": True,
            }

            def resultat_ia(provider, prompt, modele, cle, schema):
                lot = vocabulaire_lots.detail()["batch"]
                return {"text": reponse(lot), "provider": provider, "model": modele,
                        "inputTokens": 10, "outputTokens": 20}

            publication = {"ok": True, "ids": [MOTS[0]["id"]],
                           "publishedAt": "2026-10-17T10:00:00Z"}
            migration = vocabulaire_automatisation.MigrationVocabulaire()
            try:
                with mock.patch.object(vocabulaire_automatisation.vocabulaire, "charger_mots",
                                       return_value=[MOTS[0]]), \
                     mock.patch.object(vocabulaire_automatisation.vocabulaire_progression,
                                       "charger_ids_connus", return_value=set()), \
                     mock.patch.object(vocabulaire_ia_config, "charger", return_value=config), \
                     mock.patch.object(vocabulaire_ia_clients, "generer",
                                       side_effect=resultat_ia) as generer, \
                     mock.patch.object(vocabulaire_publication, "publier",
                                       return_value=publication):
                    migration.demarrer("", 1)
                    migration._thread.join(timeout=3)
                etat = migration._etat
                self.assertEqual(etat["status"], "completed")
                self.assertEqual(etat["processed"], 1)
                self.assertEqual(etat["published"], 1)
                self.assertEqual([appel.args[0] for appel in generer.call_args_list],
                                 ["gemini", "openai"])
            finally:
                vocabulaire_stockage.DOSSIER = ancien_dossier
                vocabulaire_stockage.CHEMIN = ancien_chemin


if __name__ == "__main__":
    unittest.main()
