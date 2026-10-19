# -*- coding: utf-8 -*-
"""Lots d'enrichissement du vocabulaire : contrat, revue et publication."""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bundles  # noqa: E402
import convertisseur_web  # noqa: E402
import vocabulaire  # noqa: E402
import vocabulaire_lots  # noqa: E402
import vocabulaire_stockage  # noqa: E402


MOTS = [
    {"id": "range_1879", "mot": "range", "type": "noun", "niveau": "B1", "traduction": "aller"},
    {"id": "afraid_0009", "mot": "afraid", "type": "adjective", "niveau": "A1", "traduction": "avoir peur"},
    {"id": "can_0210", "mot": "can", "type": "modal_verb", "niveau": "A1", "traduction": "pouvoir"},
]


def proposition(source, **changements):
    pos = source["type"] if source["type"] in {
        "noun", "verb", "adjective", "adverb", "preposition", "modal_verb"
    } else "other"
    valeur = {
        "id": source["id"], "originalWord": source["mot"],
        "originalTranslation": source["traduction"], "originalType": source["type"],
        "lemma": source["mot"],
        "displayForm": f"to {source['mot']}" if pos == "verb" else source["mot"],
        "partOfSpeech": pos, "primaryTranslation": "gamme" if source["id"] == "range_1879" else source["traduction"],
        "translationStatus": "incorrect", "reviewRequired": False, "reviewNote": None,
        "senses": [{"senseKey": "main", "partOfSpeech": pos,
                    "translation": "gamme" if source["id"] == "range_1879" else source["traduction"],
                    "exampleEn": f"A useful example with {source['mot']}.",
                    "exampleFr": "Un exemple utile."}],
        "collocations": [],
    }
    valeur.update(changements)
    return valeur


def reponse(lot, ids=None, changements=None):
    sources = {item["id"]: item for item in lot["sourceEntries"]}
    ids = ids or lot["ids"]
    entries = []
    for identifiant in ids:
        source = sources[identifiant]
        mot = {"id": source["id"], "mot": source["word"], "traduction": source["translation"],
               "type": source["type"], "niveau": source["cefr"]}
        entries.append(proposition(mot, **((changements or {}).get(identifiant, {}))))
    return json.dumps({"schemaVersion": 1, "batchId": lot["batchId"], "entries": entries}, ensure_ascii=False)


class BaseVocabulaire(unittest.TestCase):
    def setUp(self):
        self.temporaire = tempfile.TemporaryDirectory()
        self.ancien_dossier, self.ancien_chemin = vocabulaire_stockage.DOSSIER, vocabulaire_stockage.CHEMIN
        vocabulaire_stockage.DOSSIER = self.temporaire.name
        vocabulaire_stockage.CHEMIN = os.path.join(self.temporaire.name, "revisions.json")
        vocabulaire.vider_cache()
        self.config = mock.patch.object(
            bundles, "charger_config_import",
            return_value=({"workerUrl": "https://worker.test", "apiSecret": "secret"}, None))

        def repondre_worker(url, donnees=None, entetes=None, methode="GET", timeout=60):
            if "/srs/progress?" in url:
                return json.dumps({"words": [{"id": "afraid_0009", "status": "known"}]})
            if methode == "DELETE" and url.endswith("/words"):
                ids = json.loads(donnees)["ids"]
                return json.dumps({"ok": True, "deleted": len(ids), "ids": ids})
            if methode == "POST" and "/admin/vocabulary/batches/" in url:
                corps = json.loads(donnees)
                return json.dumps({"ok": True, "batchId": corps["batchId"],
                                   "ids": [item["id"] for item in corps["entries"]],
                                   "versions": {item["id"]: 1 for item in corps["entries"]},
                                   "publishedAt": "2026-10-16T12:00:00Z"})
            return json.dumps({"words": MOTS, "count": len(MOTS)})

        self.config.start()
        self.reseau = mock.patch.object(bundles, "_requete_worker", side_effect=repondre_worker)
        self.requete_worker = self.reseau.start()

    def tearDown(self):
        self.reseau.stop(); self.config.stop()
        vocabulaire_stockage.DOSSIER, vocabulaire_stockage.CHEMIN = self.ancien_dossier, self.ancien_chemin
        vocabulaire.vider_cache(); self.temporaire.cleanup()


class TestLotsVocabulaire(BaseVocabulaire):
    def test_filtre_connaissance_et_recherche(self):
        connus = vocabulaire.chercher_mots(connaissance="known")
        inconnus = vocabulaire.chercher_mots("range", "B1", connaissance="not_known")
        self.assertEqual([item["id"] for item in connus["items"]], ["afraid_0009"])
        self.assertEqual([item["id"] for item in inconnus["items"]], ["range_1879"])
        self.assertEqual(connus["knownTotal"], 1)

    def test_selection_automatique_est_stable_et_exclut_les_lots_existants(self):
        premiers = vocabulaire.selectionner_prochains(10, connaissance="not_known")
        self.assertEqual(premiers, ["can_0210", "range_1879"])
        self.assertEqual([mot["id"] for mot in vocabulaire.detailler_mots(premiers)], premiers)
        vocabulaire.creer_lot(["can_0210"])
        self.assertEqual(vocabulaire.selectionner_prochains(10, connaissance="not_known"), ["range_1879"])

    def test_prompt_fixe_identite_schema_et_donnees_originales(self):
        lot = vocabulaire.creer_lot(["range_1879"])
        self.assertIn(lot["batchId"], lot["prompt"])
        self.assertIn('"translation": "aller"', lot["prompt"])
        self.assertIn('"schemaVersion": 1', lot["prompt"])
        self.assertEqual(len(lot["promptHash"]), 64)

    def test_import_partiel_conserve_les_entrees_valides(self):
        lot = vocabulaire.creer_lot(["range_1879", "afraid_0009"])
        detail = vocabulaire_lots.importer(lot["batchId"], reponse(lot, ["range_1879"]))
        self.assertIn("range_1879", detail["batch"]["entries"])
        self.assertEqual(detail["batch"]["missing"], ["afraid_0009"])
        self.assertEqual(detail["batch"]["status"], "validation_failed")

    def test_refuse_un_batch_ou_une_origine_modifiee(self):
        lot = vocabulaire.creer_lot(["range_1879"])
        mauvais_batch = json.loads(reponse(lot)); mauvais_batch["batchId"] = "autre"
        detail = vocabulaire_lots.importer(lot["batchId"], json.dumps(mauvais_batch))
        self.assertTrue(any("batchId" in erreur for erreur in detail["batch"]["errors"]))
        origine = {"range_1879": {"originalTranslation": "autre"}}
        detail = vocabulaire_lots.importer(lot["batchId"], reponse(lot, changements=origine))
        self.assertTrue(any("donnée source" in erreur for erreur in detail["batch"]["errors"]))

    def test_modal_avec_to_est_refuse(self):
        lot = vocabulaire.creer_lot(["can_0210"])
        detail = vocabulaire_lots.importer(
            lot["batchId"], reponse(lot, changements={"can_0210": {"displayForm": "to can"}}))
        self.assertNotIn("can_0210", detail["batch"]["entries"])
        self.assertTrue(any("modal" in erreur for erreur in detail["batch"]["errors"]))

    def test_changement_de_categorie_impose_une_revue(self):
        lot = vocabulaire.creer_lot(["range_1879"])
        changements = {"range_1879": {"partOfSpeech": "verb", "displayForm": "to range"}}
        detail = vocabulaire_lots.importer(lot["batchId"], reponse(lot, changements=changements))
        self.assertEqual(detail["batch"]["entries"]["range_1879"]["status"], "review_required")

    def test_expression_est_acceptee_et_tout_peut_etre_approuve(self):
        lot = vocabulaire.creer_lot(["range_1879", "afraid_0009"])
        changements = {"range_1879": {"collocations": [{
            "en": "not at all", "fr": "pas du tout",
            "kind": "expression", "senseKey": "main",
        }]}}
        detail = vocabulaire_lots.importer(
            lot["batchId"], reponse(lot, changements=changements))
        self.assertFalse(detail["batch"]["errors"])
        approuve = vocabulaire_lots.approuver_tout(lot["batchId"])
        self.assertEqual(approuve["approved"], 2)
        self.assertTrue(all(item["status"] == "ready_to_publish"
                            for item in approuve["batch"]["entries"].values()))

    def test_conjonction_est_acceptee_dans_entree_et_sens(self):
        lot = vocabulaire.creer_lot(["range_1879"])
        changements = {"range_1879": {
            "partOfSpeech": "conjunction",
            "senses": [{
                "senseKey": "main", "partOfSpeech": "conjunction",
                "translation": "bien que",
                "exampleEn": "Although it was late, we continued.",
                "exampleFr": "Bien qu'il soit tard, nous avons continué.",
            }],
            "primaryTranslation": "bien que",
        }}
        detail = vocabulaire_lots.importer(
            lot["batchId"], reponse(lot, changements=changements))
        self.assertFalse(detail["batch"]["errors"])
        entree = detail["batch"]["entries"]["range_1879"]["proposed"]
        self.assertEqual(entree["partOfSpeech"], "conjunction")
        self.assertEqual(entree["senses"][0]["partOfSpeech"], "conjunction")

    def test_tout_type_grammatical_non_vide_est_accepte(self):
        lot = vocabulaire.creer_lot(["range_1879"])
        changements = {"range_1879": {
            "partOfSpeech": "subordinating_conjunction",
            "senses": [{
                "senseKey": "main",
                "partOfSpeech": "discourse_marker",
                "translation": "bien que",
                "exampleEn": "Although it was late, we continued.",
                "exampleFr": "Bien qu'il soit tard, nous avons continué.",
            }],
            "primaryTranslation": "bien que",
        }}
        detail = vocabulaire_lots.importer(
            lot["batchId"], reponse(lot, changements=changements))
        self.assertFalse(detail["batch"]["errors"])
        entree = detail["batch"]["entries"]["range_1879"]["proposed"]
        self.assertEqual(entree["partOfSpeech"], "subordinating_conjunction")
        self.assertEqual(entree["senses"][0]["partOfSpeech"], "discourse_marker")

    def test_approbation_puis_publication_versionnee(self):
        lot = vocabulaire.creer_lot(["range_1879"])
        vocabulaire_lots.importer(lot["batchId"], reponse(lot))
        vocabulaire_lots.changer_statut(lot["batchId"], "range_1879", "ready_to_publish")
        resultat = vocabulaire_lots.publier(lot["batchId"])
        self.assertEqual(resultat["ids"], ["range_1879"])
        self.assertEqual(vocabulaire_lots.detail(lot["batchId"])["batch"]["status"], "published")
        appel = next(item for item in self.requete_worker.call_args_list
                     if item.kwargs.get("methode") == "POST")
        self.assertTrue(appel.args[0].endswith(f"/{lot['batchId']}/publish"))

    def test_publication_partielle_exige_un_accord_explicite(self):
        lot = vocabulaire.creer_lot(["range_1879", "afraid_0009"])
        vocabulaire_lots.importer(lot["batchId"], reponse(lot))
        vocabulaire_lots.changer_statut(lot["batchId"], "range_1879", "ready_to_publish")
        with self.assertRaisesRegex(ValueError, "partielle"):
            vocabulaire_lots.publier(lot["batchId"])
        resultat = vocabulaire_lots.publier(lot["batchId"], partiel=True)
        self.assertEqual(resultat["ids"], ["range_1879"])

    def test_suppression_lot_non_publie_libere_les_mots(self):
        lot = vocabulaire.creer_lot(["range_1879"])
        self.assertNotIn("range_1879", vocabulaire.selectionner_prochains(10))
        detail = vocabulaire_lots.supprimer(lot["batchId"])
        self.assertIsNone(detail["batch"])
        self.assertIn("range_1879", vocabulaire.selectionner_prochains(10))

    def test_suppression_lot_publie_est_interdite(self):
        lot = vocabulaire.creer_lot(["range_1879"])
        vocabulaire_lots.importer(lot["batchId"], reponse(lot))
        vocabulaire_lots.changer_statut(lot["batchId"], "range_1879", "ready_to_publish")
        vocabulaire_lots.publier(lot["batchId"])
        with self.assertRaisesRegex(ValueError, "déjà publié"):
            vocabulaire_lots.supprimer(lot["batchId"])

    def test_suppression_reste_une_action_distincte(self):
        resultat = vocabulaire.supprimer_mots(["range_1879"])
        self.assertEqual(resultat["deleted"], 1)
        appel = next(item for item in self.requete_worker.call_args_list
                     if item.kwargs.get("methode") == "DELETE")
        self.assertEqual(json.loads(appel.kwargs["donnees"]), {"ids": ["range_1879"]})


class TestRoutesVocabulaire(BaseVocabulaire):
    def setUp(self):
        super().setUp()
        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), convertisseur_web.Gestionnaire)
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.serveur.server_address[1]}"

    def tearDown(self):
        self.serveur.shutdown(); self.serveur.server_close(); super().tearDown()

    def poster(self, chemin, corps):
        requete = urllib.request.Request(self.base + chemin, data=json.dumps(corps).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(requete, timeout=10) as reponse_http:
            return json.loads(reponse_http.read())

    def test_cycle_http_lot_import_revue_publication(self):
        lot = self.poster("/api/vocabulaire/lot", {"ids": ["range_1879"]})["batch"]
        importe = self.poster("/api/vocabulaire/lot/importer", {"batchId": lot["batchId"], "texte": reponse(lot)})
        self.assertIn("range_1879", importe["batch"]["entries"])
        self.poster("/api/vocabulaire/lot/statut", {"batchId": lot["batchId"], "id": "range_1879", "statut": "ready_to_publish"})
        publication = self.poster("/api/vocabulaire/lot/publier", {"batchId": lot["batchId"]})
        self.assertEqual(publication["publication"]["ids"], ["range_1879"])

    def test_page_et_api_sont_accessibles(self):
        with urllib.request.urlopen(self.base + "/vocabulaire", timeout=10) as reponse_http:
            self.assertIn("Enrichissement du vocabulaire", reponse_http.read().decode())
        with urllib.request.urlopen(self.base + "/api/vocabulaire/mots?q=range", timeout=10) as reponse_http:
            self.assertEqual(json.loads(reponse_http.read())["items"][0]["id"], "range_1879")


if __name__ == "__main__":
    unittest.main()
