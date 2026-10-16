# -*- coding: utf-8 -*-
"""Idées de contenus : recherche YouTube via le Worker (requêtes simulées).

Lancement :  python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import unittest
import urllib.parse
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bundles             # noqa: E402
import convertisseur_web   # noqa: E402
import idees               # noqa: E402
from test_pipeline import BaseBundle  # noqa: E402

CONFIG = {"workerUrl": "https://w", "apiSecret": "secret", "profileId": "default"}

RECHERCHE = {"items": [
    {"id": {"kind": "youtube#video", "videoId": "aaaaaaaaaaa"}},
    {"id": {"kind": "youtube#video", "videoId": "bbbbbbbbbbb"}},
    {"id": {"kind": "youtube#video", "videoId": "ccccccccccc"}},
]}
VIDEOS = {"items": [
    {"id": "bbbbbbbbbbb",
     "snippet": {"title": "How LLMs work", "channelTitle": "Chaîne B",
                 "publishedAt": "2026-03-01T10:00:00Z",
                 "defaultAudioLanguage": "en-GB",
                 "thumbnails": {"default": {"url": "d.jpg"},
                                "medium": {"url": "m.jpg"}},
                 "description": "très longue description non renvoyée"},
     "contentDetails": {"duration": "PT12M5S"},
     "statistics": {"viewCount": "125000", "likeCount": "10"}},
    {"id": "aaaaaaaaaaa",
     "snippet": {"title": "AI in 2026", "channelTitle": "Chaîne A",
                 "publishedAt": "2026-05-01T10:00:00Z"},
     "contentDetails": {"duration": "PT1H2M3S"},
     "statistics": {}},
    # ccccccccccc absente : vidéo devenue privée entre search et videos
]}


def faux_worker(appels):
    def repondre(url, entetes=None, **_options):
        appels.append((url, entetes))
        chemin = urllib.parse.urlsplit(url).path
        return json.dumps(RECHERCHE if chemin == "/youtube/search" else VIDEOS)
    return repondre


class BaseIdees(unittest.TestCase):
    def setUp(self):
        idees.vider_cache()
        self.appels = []
        self.reseau = mock.patch.object(bundles, "_requete_worker",
                                        side_effect=faux_worker(self.appels))
        self.reseau.start()
        self.config = mock.patch.object(bundles, "charger_config_import",
                                        return_value=(dict(CONFIG), None))
        self.config.start()

    def tearDown(self):
        self.reseau.stop()
        self.config.stop()
        idees.vider_cache()


class TestUtilitaires(unittest.TestCase):
    def test_id_video(self):
        for url in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "https://youtube.com/watch?feature=x&v=dQw4w9WgXcQ&t=3",
                    "https://youtu.be/dQw4w9WgXcQ?si=abc",
                    "https://m.youtube.com/shorts/dQw4w9WgXcQ",
                    "https://www.youtube.com/embed/dQw4w9WgXcQ"):
            self.assertEqual(idees.id_video(url), "dQw4w9WgXcQ", url)
        for url in ("https://y/slug", "", None, "https://vimeo.com/12345678901",
                    "https://www.youtube.com/watch?v=court"):
            self.assertIsNone(idees.id_video(url), url)

    def test_secondes_iso(self):
        self.assertEqual(idees.secondes_iso("PT12M5S"), 725)
        self.assertEqual(idees.secondes_iso("PT1H2M3S"), 3723)
        self.assertEqual(idees.secondes_iso("PT45S"), 45)
        self.assertEqual(idees.secondes_iso("P1DT1S"), 86401)
        self.assertIsNone(idees.secondes_iso("P"))
        self.assertIsNone(idees.secondes_iso(None))


class TestRecherche(BaseIdees):
    def test_parametres_envoyes_au_worker(self):
        idees.rechercher("  artificial   intelligence ", "en", "moyenne")
        self.assertEqual(len(self.appels), 2)
        url, entetes = self.appels[0]
        morceaux = urllib.parse.urlsplit(url)
        p = dict(urllib.parse.parse_qsl(morceaux.query))
        self.assertEqual(morceaux.netloc + morceaux.path, "w/youtube/search")
        self.assertEqual(entetes["Authorization"], "Bearer secret")
        self.assertEqual(p["q"], "artificial intelligence")
        self.assertEqual(p["type"], "video")
        self.assertEqual(p["relevanceLanguage"], "en")
        self.assertEqual(p["videoDuration"], "medium")
        self.assertEqual(p["videoCaption"], "any")
        self.assertLessEqual(int(p["maxResults"]), 15)
        self.assertNotIn("key", p)

        url, entetes = self.appels[1]
        p = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.assertTrue(url.startswith("https://w/youtube/videos?"))
        self.assertEqual(p["part"], "contentDetails,snippet,statistics")
        self.assertEqual(p["id"], "aaaaaaaaaaa,bbbbbbbbbbb,ccccccccccc")
        self.assertEqual(entetes["Authorization"], "Bearer secret")

    def test_durees_et_maximum(self):
        idees.rechercher("x", "fr", "longue", maximum=50)
        p = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.appels[0][0]).query))
        self.assertEqual(p["videoDuration"], "long")
        self.assertEqual(p["relevanceLanguage"], "fr")
        self.assertEqual(p["maxResults"], "15")

    def test_champs_utiles_seulement_dans_l_ordre(self):
        resultats, cache = idees.rechercher("ai", "en", "moyenne")
        self.assertFalse(cache)
        self.assertEqual([r["id"] for r in resultats], ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        b = resultats[1]
        self.assertEqual(set(b), {"id", "url", "titre", "chaine", "miniature",
                                  "duree", "date", "langue", "vues"})
        self.assertEqual(b["url"], "https://www.youtube.com/watch?v=bbbbbbbbbbb")
        self.assertEqual(b["miniature"], "m.jpg")
        self.assertEqual(b["duree"], 725)
        self.assertEqual(b["langue"], "en")
        self.assertEqual(b["vues"], 125000)
        a = resultats[0]
        self.assertIsNone(a["langue"])
        self.assertIsNone(a["vues"])
        self.assertIsNone(a["miniature"])

    def test_cache_une_heure(self):
        horloge = [1000.0]
        maintenant = lambda: horloge[0]  # noqa: E731
        idees.rechercher("AI", "en", "moyenne", maintenant=maintenant)
        r, cache = idees.rechercher("ai", "en", "moyenne", maintenant=maintenant)
        self.assertTrue(cache)
        self.assertEqual(len(self.appels), 2)        # aucun nouvel appel
        r[0]["titre"] = "modifié"                     # copie, pas l'original
        r, _ = idees.rechercher("ai", "en", "moyenne", maintenant=maintenant)
        self.assertEqual(r[0]["titre"], "AI in 2026")
        idees.rechercher("ai", "en", "courte", maintenant=maintenant)
        self.assertEqual(len(self.appels), 4)        # filtres différents
        horloge[0] += 3601
        _, cache = idees.rechercher("ai", "en", "moyenne", maintenant=maintenant)
        self.assertFalse(cache)
        self.assertEqual(len(self.appels), 6)        # expiré : nouvel appel

    def test_aucun_resultat_un_seul_appel(self):
        with mock.patch.object(bundles, "_requete_worker",
                               return_value='{"items": []}') as requete:
            resultats, _ = idees.rechercher("zzz", "en", "moyenne")
        self.assertEqual(resultats, [])
        self.assertEqual(requete.call_count, 1)

    def test_parametres_invalides(self):
        for args in (("", "en", "moyenne"), ("x", "de", "moyenne"),
                     ("x", "en", "infinie")):
            with self.assertRaises(ValueError):
                idees.rechercher(*args)
        self.assertEqual(self.appels, [])

    def test_erreurs_worker(self):
        with mock.patch.object(bundles, "_requete_worker",
                               side_effect=RuntimeError("HTTP 429 — quota")):
            with self.assertRaises(RuntimeError):
                idees.rechercher("x", "en", "moyenne")
        with mock.patch.object(bundles, "charger_config_import",
                               return_value=(None, "config absente")):
            with self.assertRaisesRegex(RuntimeError, "config absente"):
                idees.rechercher("y", "en", "moyenne")

    def test_echec_non_mis_en_cache(self):
        with mock.patch.object(bundles, "_requete_worker",
                               side_effect=RuntimeError("HTTP 500")):
            with self.assertRaises(RuntimeError):
                idees.rechercher("x", "en", "moyenne")
        _, cache = idees.rechercher("x", "en", "moyenne")
        self.assertFalse(cache)


class TestRouteServeur(BaseIdees, BaseBundle):
    def setUp(self):
        BaseBundle.setUp(self)
        BaseIdees.setUp(self)
        self.jobs = mock.patch.object(convertisseur_web, "JOBS",
                                      convertisseur_web.FileJobs())
        self.jobs.start()

    def tearDown(self):
        self.jobs.stop()
        BaseIdees.tearDown(self)
        BaseBundle.tearDown(self)

    def test_presence_bibliotheque_et_preparation(self):
        meta = bundles.construire_meta(
            "deja", "AI in 2026", "https://youtu.be/aaaaaaaaaaa", "en", "en",
            "B1", "tech", statut="prepared")
        bundles.ecrire_meta("deja", meta)
        job = convertisseur_web.Job("job-1", idees.url_video("bbbbbbbbbbb"),
                                    "en", "B1", None)
        convertisseur_web.JOBS.jobs.append(job)

        code, corps = convertisseur_web.chercher_idees(
            {"q": "artificial intelligence", "langue": "en", "duree": "moyenne"})
        self.assertEqual(code, 200)
        presence = {r["id"]: r["presence"] for r in corps["resultats"]}
        self.assertEqual(presence, {"aaaaaaaaaaa": "bibliotheque",
                                    "bbbbbbbbbbb": "preparation"})

        job.statut = "failed"          # un job échoué n'empêche pas l'ajout
        code, corps = convertisseur_web.chercher_idees(
            {"q": "artificial intelligence", "langue": "en", "duree": "moyenne"})
        self.assertTrue(corps["cache"])
        self.assertIsNone(corps["resultats"][1]["presence"])

    def test_codes_erreur(self):
        code, corps = convertisseur_web.chercher_idees({"q": ""})
        self.assertEqual(code, 400)
        with mock.patch.object(bundles, "_requete_worker",
                               side_effect=RuntimeError("worker injoignable")):
            code, corps = convertisseur_web.chercher_idees({"q": "x"})
        self.assertEqual(code, 502)
        self.assertIn("worker injoignable", corps["erreur"])


if __name__ == "__main__":
    unittest.main()
