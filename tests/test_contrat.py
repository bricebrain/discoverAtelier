# -*- coding: utf-8 -*-
"""Non-régression LOT 0 — contrats de l'atelier.

1. Le payload publié garde tous les champs lus par la PWA et le Worker
   (src/helpers/preparedContent.ts, src/api/learningApi.ts, POST /content).
2. Les routes du serveur local utilisées par l'interface répondent.
"""

import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import convertisseur_web  # noqa: E402
import pipeline  # noqa: E402
from test_pipeline import BaseBundle  # noqa: E402

# Champs historiques : la PWA les lit pour les contenus déjà publiés
CHAMPS_RACINE = {"profileId", "id", "type", "title", "level", "topic", "body", "audioR2Key", "metadata"}
CHAMPS_METADATA_HISTORIQUES = {"sourceType", "sourceUrl", "audioLanguage", "transcriptLanguage", "transcriptText"}
CHAMPS_METADATA_V2 = {"schemaVersion", "sourceLanguage", "learningLanguage", "targetLocale", "audioOrigin",
                      "contentRevision", "textEn", "textFr", "segments", "chunks", "grammarPoints"}


class TestContratPayload(BaseBundle):
    def test_payload_source_fr(self):
        self.bundle_fr_complet("v")
        self.generer_tts("v")
        payload, _etat, erreur = pipeline.payload_distant("v")
        self.assertIsNone(erreur)
        self.assertEqual(set(payload), CHAMPS_RACINE)
        self.assertTrue(CHAMPS_METADATA_HISTORIQUES <= set(payload["metadata"]))
        self.assertTrue(CHAMPS_METADATA_V2 <= set(payload["metadata"]))
        self.assertEqual(payload["type"], "podcast")              # type accepté par le Worker
        self.assertEqual(payload["metadata"]["audioLanguage"], "en")
        self.assertEqual(payload["metadata"]["audioOrigin"], "kokoro_tts")
        # LOT 1 : clé immuable prepared-content/<id>-faithful-<audioRevision>.mp3
        self.assertRegex(payload["audioR2Key"], r"^prepared-content/v-faithful-[0-9a-f]{8}\.mp3$")
        self.assertRegex(payload["audioR2Key"], r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")  # règle de clé du Worker
        for segment in payload["metadata"]["segments"]:
            self.assertEqual(set(segment), {"id", "en", "fr", "startMs", "endMs"})

    def test_payload_source_en(self):
        segments = self.creer("e", "en", "We need to figure it out.")
        pipeline.enregistrer_traduction("e", self.traduction(segments, "FR"))
        pipeline.enregistrer_pedagogie("e", self.pedagogie())
        payload, _etat, erreur = pipeline.payload_distant("e")
        self.assertIsNone(erreur)
        self.assertRegex(payload["audioR2Key"], r"^prepared-content/e-faithful-[0-9a-f]{8}\.mp3$")
        self.assertEqual(payload["metadata"]["audioOrigin"], "original")
        self.assertEqual(payload["metadata"]["transcriptLanguage"], "en")

    def test_payload_serialisable_en_json(self):
        self.bundle_fr_complet("v")
        self.generer_tts("v")
        payload, _etat, _ = pipeline.payload_distant("v")
        self.assertEqual(json.loads(json.dumps(payload)), payload)


class TestServeurLocal(BaseBundle):
    def setUp(self):
        super().setUp()
        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), convertisseur_web.Gestionnaire)
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.serveur.server_address[1]}"

    def tearDown(self):
        self.serveur.shutdown()
        self.serveur.server_close()
        super().tearDown()

    def get(self, chemin):
        with urllib.request.urlopen(self.base + chemin, timeout=10) as reponse:
            return reponse.status, reponse.read()

    def test_page_et_routes_de_lecture(self):
        self.bundle_fr_complet("v")
        statut, page = self.get("/?r=1")
        self.assertEqual(statut, 200)
        self.assertIn(b"Atelier English Fluency", page)
        statut, corps = self.get("/api/bundles")
        self.assertEqual([b["slug"] for b in json.loads(corps)["bundles"]], ["v"])
        statut, corps = self.get("/api/bundle?slug=v")
        detail = json.loads(corps)
        self.assertEqual(detail["etat"]["statut"], "awaiting_tts")
        self.assertEqual(detail["traduction"]["faits"], detail["traduction"]["total"])
        statut, _ = self.get("/api/jobs")
        self.assertEqual(statut, 200)

    def test_audio_avec_range(self):
        self.bundle_fr_complet("v")
        requete = urllib.request.Request(self.base + "/api/audio?slug=v&quel=original", headers={"Range": "bytes=0-9"})
        with urllib.request.urlopen(requete, timeout=10) as reponse:
            self.assertEqual(reponse.status, 206)
            self.assertEqual(len(reponse.read()), 10)


if __name__ == "__main__":
    unittest.main()
