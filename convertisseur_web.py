#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Atelier English Fluency — application locale à interface web.

Serveur web minimal (bibliothèque standard uniquement) : une vidéo
YouTube FR ou EN devient un bundle bilingue publiable (audio anglais,
textes EN/FR intégraux, chunks, grammaire). La logique métier vit dans
pipeline.py ; ce fichier pilote yt-dlp, la transcription, Kokoro et
sert l'interface. Le navigateur s'ouvre automatiquement au lancement.

Dépendances (à installer une fois) :
    python3 -m pip install --user -r requirements.txt

Lancement :
    python3 convertisseur_web.py   (ou double-clic sur « lancer_atelier.command »)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# Dépendances externes
# ---------------------------------------------------------------------------
try:
    import yt_dlp
except ImportError:
    print("❌ Le module yt-dlp est absent. Installez les dépendances avec :")
    print("   python3 -m pip install --user -r requirements.txt")
    sys.exit(1)

import transcription  # sous-titres YouTube + MacWhisper (même dossier)
import bundles        # fichiers des bundles + connexion Worker (même dossier)
import idees          # idées de contenus : recherche YouTube via le Worker
import pipeline       # logique métier bilingue : prompts, validation, canPublish


CHEMIN_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "interface.html")


def trouver_ffmpeg():
    """Localise ffmpeg : d'abord dans le PATH, sinon via imageio-ffmpeg."""
    chemin = shutil.which("ffmpeg")
    if chemin:
        return chemin
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Atelier : file de jobs (un job par lien YouTube — spec §10)
# ---------------------------------------------------------------------------
class Job:
    def __init__(self, identifiant, url, langue_audio, niveau, theme,
                 auto_publier=False):
        self.id = identifiant
        self.auto_publier = auto_publier
        self.url = url
        self.langue_audio = langue_audio    # "auto" | "fr" | "en"
        self.niveau = niveau                # A2 | B1 | B2
        self.theme = theme                  # valeur anglaise ou None
        self.titre = ""
        self.slug = None
        self.statut = "queued"
        self.progression = None             # 0-100 ou None
        self.message = ""

    def instantane(self):
        return {"id": self.id, "url": self.url, "titre": self.titre,
                "slug": self.slug, "statut": self.statut,
                "langue": self.langue_audio, "niveau": self.niveau,
                "theme": self.theme, "autoPublish": self.auto_publier,
                "progression": self.progression, "message": self.message}

    @classmethod
    def depuis(cls, donnees):
        job = cls(donnees["id"], donnees["url"], donnees.get("langue", "auto"),
                  donnees.get("niveau", "B1"), donnees.get("theme"),
                  donnees.get("autoPublish", False))
        job.titre = donnees.get("titre", "")
        job.slug = donnees.get("slug")
        job.statut = donnees.get("statut", "failed")
        job.message = donnees.get("message", "")
        job.progression = donnees.get("progression")
        return job


def chemin_jobs():
    return os.path.join(bundles.DOSSIER_BUNDLES, "_jobs.json")

STATUTS_EN_COURS = ("queued", "extracting", "transcribing")


class FileJobs:
    """File de traitement séquentielle : une vidéo à la fois. Chaque URL
    a son propre job et son propre bundle ; un échec n'arrête pas les
    autres."""

    def __init__(self):
        self.verrou = threading.Lock()
        self.jobs = []
        self.file = []
        self._compteur = 0
        self._thread_actif = False

    def ajouter(self, url, langue_audio, niveau, theme, auto_publier=False):
        with self.verrou:
            existant = next(
                (j for j in self.jobs
                 if j.url == url and j.statut not in ("failed",)), None)
            if existant:
                return existant, True
            self._compteur += 1
            job = Job(f"job-{self._compteur}", url, langue_audio,
                      niveau, theme, auto_publier)
            self.jobs.append(job)
            self.file.append(job)
        self.sauvegarder()
        self._demarrer()
        return job, False

    def relancer(self, identifiant, langue_audio=None):
        with self.verrou:
            job = next((j for j in self.jobs if j.id == identifiant), None)
            if not job or job.statut not in ("failed",):
                return None
            if langue_audio in ("fr", "en"):
                job.langue_audio = langue_audio
            job.statut = "queued"
            job.message = ""
            job.progression = None
            self.file.append(job)
        self.sauvegarder()
        self._demarrer()
        return job

    def sauvegarder(self):
        """Persiste la file : un redémarrage ne perd aucun job."""
        with self.verrou:
            donnees = [j.instantane() for j in self.jobs[-100:]]
        try:
            bundles.assure_dossier()
            pipeline.ecrire_json(chemin_jobs(), {"jobs": donnees})
        except OSError:
            pass

    def charger(self):
        """Recharge les jobs au démarrage. Ceux qui tournaient au moment
        de l'arrêt passent en échec « interrompu » avec Relancer (l'audio
        déjà extrait n'est pas re-téléchargé)."""
        donnees = pipeline.lire_json(chemin_jobs()) or {}
        with self.verrou:
            for element in donnees.get("jobs", []):
                try:
                    job = Job.depuis(element)
                except (KeyError, TypeError):
                    continue
                if job.statut in STATUTS_EN_COURS:
                    job.statut = "failed"
                    job.progression = None
                    job.message = ("interrompu par un redémarrage — "
                                   "cliquez sur Relancer")
                self.jobs.append(job)
                numero = job.id.rsplit("-", 1)[-1]
                if numero.isdigit():
                    self._compteur = max(self._compteur, int(numero))
        self.sauvegarder()

    def _demarrer(self):
        with self.verrou:
            if self._thread_actif:
                return
            self._thread_actif = True
        threading.Thread(target=self._boucle, daemon=True).start()

    def _boucle(self):
        while True:
            with self.verrou:
                if not self.file:
                    self._thread_actif = False
                    return
                job = self.file.pop(0)
            traiter_job(job, signaler=self.sauvegarder)
            self.sauvegarder()

    def instantane(self):
        with self.verrou:
            return [j.instantane() for j in reversed(self.jobs)]

    def masquer(self, identifiant):
        """Retire de la liste un job terminé, échoué ou doublon."""
        with self.verrou:
            avant = len(self.jobs)
            self.jobs = [j for j in self.jobs
                         if j.id != identifiant or j.statut in STATUTS_EN_COURS]
            retire = len(self.jobs) != avant
        if retire:
            self.sauvegarder()
        return retire

    def slugs_en_preparation(self):
        with self.verrou:
            return {j.slug for j in self.jobs
                    if j.slug and j.statut in STATUTS_EN_COURS}


JOBS = FileJobs()


def detecter_langue(info):
    """'fr' ou 'en' d'après les infos YouTube, sinon None.
    La piste automatique « <langue>-orig » désigne la langue parlée."""
    langue = (info.get("language") or "")[:2].lower()
    if langue in ("fr", "en"):
        return langue
    for code in info.get("automatic_captions") or {}:
        if code.endswith("-orig") and code[:2] in ("fr", "en"):
            return code[:2]
    manuelles = [c[:2] for c in info.get("subtitles") or {}
                 if c[:2] in ("fr", "en")]
    if len(set(manuelles)) == 1:
        return manuelles[0]
    return None


def transcrire_pour_atelier(job, base):
    """Écrit <slug>.transcript.<langue source>.txt avec MacWhisper (local),
    dans la langue de la vidéo. Les sous-titres YouTube ne sont pas
    utilisés. Renvoie la source."""
    chemin_txt, source = transcription.transcrire_macwhisper(
        base + ".mp3", base + f".transcript.{job.langue_audio}",
        job.langue_audio)
    if not chemin_txt:
        raise RuntimeError(f"transcription MacWhisper impossible : {source}")
    return source


def message_lisible(erreur):
    """Retire les codes couleur du terminal (yt-dlp) d'un message."""
    return re.sub(r"\x1b\[[0-9;]*m", "", str(erreur)).strip()


def traiter_job(job, signaler=lambda: None):
    """Traite un job : télécharge l'audio original, transcrit, écrit le
    bundle. La suite (traduction, analyse, audio EN) est guidée dans
    l'interface."""
    try:
        job.statut = "extracting"
        signaler()
        ffmpeg = trouver_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("ffmpeg introuvable")
        bundles.assure_dossier()

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                               "noprogress": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(job.url, download=False) or {}
        job.titre = info.get("title") or job.url
        if job.langue_audio == "auto":
            detectee = detecter_langue(info)
            if not detectee:
                raise RuntimeError("langue non détectée : relancez en "
                                   "choisissant Français ou Anglais")
            job.langue_audio = detectee
        if not job.slug:
            slug, doublon = bundles.slug_disponible(
                bundles.slugifier(job.titre), job.url)
            if not slug:
                job.statut = "doublon"
                job.message = f"déjà présent : {doublon}"
                return
            job.slug = slug
        base = os.path.join(bundles.DOSSIER_BUNDLES, job.slug)

        def hook(d):
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                job.progression = min(
                    d.get("downloaded_bytes", 0) / total * 100, 100)

        # Reprise : l'audio original déjà extrait n'est pas re-téléchargé
        if not pipeline.audio_lisible(base + ".mp3"):
            options = {
                "format": "bestaudio/best",
                "noplaylist": True,
                "default_search": "error",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "outtmpl": base + ".%(ext)s",
                "ffmpeg_location": ffmpeg,
                "quiet": True, "no_warnings": True, "noprogress": True,
                "progress_hooks": [hook],
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([job.url])
            if not os.path.exists(base + ".mp3"):
                raise RuntimeError("le MP3 n'a pas été produit")

        job.statut = "transcribing"
        job.progression = None
        job.message = ("MacWhisper transcrit l'audio "
                       f"({'français' if job.langue_audio == 'fr' else 'anglais'})… "
                       "cela peut prendre plusieurs minutes")
        signaler()
        source = transcrire_pour_atelier(job, base)

        meta = bundles.construire_meta(
            job.slug, job.titre, job.url, job.langue_audio, job.langue_audio,
            job.niveau, job.theme, statut="prepared",
            auto_publier=job.auto_publier)
        meta["processing"] = {"transcriptionProvider": source}
        meta["sourceRevision"] = pipeline.revision_source_bundle(job.slug, {})
        bundles.ecrire_meta(job.slug, meta)
        bundles.rafraichir_meta(job.slug)
        pipeline.initialiser_segments(job.slug)

        job.statut = "awaiting_translation"
        job.progression = 100
        job.message = f"{job.langue_audio.upper()} · transcription : {source}"
    except Exception as e:
        job.statut = "failed"
        job.message = message_lisible(e)
        # Écrit quand même le meta pour ne pas laisser de bundle orphelin
        # (un .mp3 sans .meta.json apparaîtrait comme « invalide »).
        if job.slug:
            meta = bundles.lire_meta(job.slug) or bundles.construire_meta(
                job.slug, job.titre or job.url, job.url,
                job.langue_audio if job.langue_audio in ("fr", "en") else None,
                "", job.niveau, job.theme)
            meta["status"] = "failed"
            meta["erreur"] = message_lisible(e)
            bundles.ecrire_meta(job.slug, meta)


# ---------------------------------------------------------------------------
# Publications vers le Worker (état partagé avec l'interface)
# ---------------------------------------------------------------------------
IMPORTS = {}  # slug -> {"statut": "en cours|ok|echec", "message": str}
VERRO_IMPORTS = threading.Lock()


def import_en_cours(slug):
    with VERRO_IMPORTS:
        return (IMPORTS.get(slug) or {}).get("statut") == "en cours"


def lancer_import(slug):
    """Lance la publication d'un bundle dans un thread, seulement si
    etat_publication(...).ok. Renvoie (ok, erreur)."""
    with VERRO_IMPORTS:
        etat = IMPORTS.get(slug)
        if etat and etat["statut"] == "en cours":
            return False, "un import est déjà en cours pour ce bundle"
        preparation = pipeline.etat_publication(slug)
        if not preparation["ok"]:
            return False, ("bundle non publiable : "
                           + " ; ".join(preparation["raisons"]))
        IMPORTS[slug] = {"statut": "en cours", "message": ""}

    def faire():
        try:
            ok, message = pipeline.publier(
                slug, signal=lambda etape: _maj_import(slug, message=etape))
        except Exception as e:
            ok, message = False, f"échec de publication : {e}"
        _maj_import(slug, statut="ok" if ok else "echec", message=message)

    threading.Thread(target=faire, daemon=True).start()
    return True, None


def apres_modification(slug):
    """À appeler après chaque changement d'un bundle (traduction ou
    analyse validée, TTS terminé) : publie automatiquement si l'option
    est active et que tous les prérequis sont réunis (§8.2, §8.4)."""
    ok, _raison = pipeline.doit_auto_publier(
        slug, import_en_cours=import_en_cours(slug))
    if ok:
        lance, _erreur = lancer_import(slug)
        if lance:
            _maj_import(slug, message="publication automatique…")
        return lance
    return False


def _maj_import(slug, statut=None, message=None):
    with VERRO_IMPORTS:
        etat = IMPORTS.setdefault(slug, {"statut": "en cours", "message": ""})
        if statut:
            etat["statut"] = statut
        if message is not None:
            etat["message"] = message


def instantane_imports():
    with VERRO_IMPORTS:
        return {slug: dict(etat) for slug, etat in IMPORTS.items()}


# ---------------------------------------------------------------------------
# Génération d'audio anglais (Kokoro TTS, via venv-tts) — source FR
# ---------------------------------------------------------------------------
VOIX_KOKORO = ["bf_emma", "bf_isabella", "bm_george", "bm_fable",
               "af_heart", "af_bella"]
CHEMIN_PYTHON_TTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "venv-tts", "bin", "python")
CHEMIN_SCRIPT_TTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tts_kokoro.py")

TTS_ETATS = {}  # slug -> {"statut", "message", "progression"}
VERRO_TTS = threading.Lock()


def _maj_tts(slug, **champs):
    with VERRO_TTS:
        TTS_ETATS.setdefault(
            slug, {"statut": "en cours", "message": "", "progression": None}
        ).update(champs)


def instantane_tts():
    with VERRO_TTS:
        return {slug: dict(etat) for slug, etat in TTS_ETATS.items()}


def lancer_tts(slug, voix):
    """Lance la génération d'audio anglais dans un thread."""
    meta = bundles.lire_meta(slug)
    if pipeline.langue_source(meta) != "fr":
        return False, ("source anglaise : l'audio original est publié, "
                       "aucun TTS n'est nécessaire")
    segments = pipeline.lire_segments(slug)
    if not segments or not all((s.get("en") or "").strip() for s in segments):
        return False, "texte anglais incomplet : terminez la traduction FR→EN"
    with VERRO_TTS:
        if TTS_ETATS.get(slug, {}).get("statut") == "en cours":
            return False, "une génération est déjà en cours pour ce bundle"
        TTS_ETATS[slug] = {"statut": "en cours", "message": "",
                           "progression": None}
    threading.Thread(target=_executer_tts, args=(slug, voix),
                     daemon=True).start()
    return True, None


def _executer_tts(slug, voix):
    base = os.path.join(bundles.DOSSIER_BUNDLES, slug)
    entree, wav = base + ".tts-input.en.json", base + ".tts.wav"
    timings_temporaires = base + ".tts-timings.json"
    mp3_temporaire = base + ".audio-en.tmp.mp3"
    try:
        if not os.path.exists(CHEMIN_PYTHON_TTS):
            raise RuntimeError("venv-tts est absent (voir README, section TTS)")
        # Kokoro lit exclusivement le texte anglais validé, segment par
        # segment : l'audio a ses propres timings (v1.2 § 6.1)
        segments = pipeline.lire_segments(slug)
        texte_en = pipeline.texte_complet(segments, "en")
        hash_en = pipeline.empreinte(texte_en)
        with open(entree, "w", encoding="utf-8") as f:
            json.dump([{"id": s["id"], "en": s["en"]} for s in segments], f,
                      ensure_ascii=False)
        ffmpeg = trouver_ffmpeg()

        pipeline.marquer_tts(slug, "generating")
        _maj_tts(slug, message="chargement du modèle Kokoro…")
        processus = subprocess.Popen(
            [CHEMIN_PYTHON_TTS, CHEMIN_SCRIPT_TTS, "--voix", voix,
             "--sortie", wav, "--segments", entree,
             "--timings", timings_temporaires],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for ligne in processus.stdout:
            ligne = ligne.strip()
            if ligne.startswith("PROGRESSION "):
                i, n = ligne.split()[1].split("/")
                _maj_tts(slug, progression=round(int(i) / int(n) * 100),
                         message=f"génération Kokoro… segment {i}/{n}")
            elif ligne.startswith("OK "):
                _maj_tts(slug, message=f"conversion MP3… ({ligne.split()[1]})")
            elif ligne.startswith("ERREUR"):
                raise RuntimeError(ligne)
        if processus.wait() != 0 or not os.path.exists(wav):
            raise RuntimeError("la génération Kokoro a échoué")

        if not ffmpeg:
            raise RuntimeError("ffmpeg introuvable pour la conversion MP3")
        conversion = subprocess.run(
            [ffmpeg, "-y", "-i", wav, "-codec:a", "libmp3lame",
             "-b:a", "128k", mp3_temporaire], capture_output=True)
        if conversion.returncode != 0 or not pipeline.audio_lisible(
                mp3_temporaire):
            raise RuntimeError("conversion MP3 échouée")
        with open(timings_temporaires, encoding="utf-8") as f:
            timings = json.load(f)
        if [t.get("id") for t in timings] != [s["id"] for s in segments]:
            raise RuntimeError("timings Kokoro incohérents avec les segments")
        # Second fichier : l'audio original <slug>.mp3 n'est jamais touché
        os.replace(mp3_temporaire, base + ".audio-en.mp3")
        pipeline.ecrire_json(base + ".audio-en.timings.json", {
            "textHash": hash_en, "voice": voix,
            "segmentationVersion": pipeline.lire_infos_segments(slug)["segmentationVersion"],
            "timings": timings})

        pipeline.enregistrer_tts(slug, hash_en, voix)
        bundles.rafraichir_meta(slug)
        _maj_tts(slug, statut="ok", progression=100,
                 message="audio anglais généré 🎧")
        apres_modification(slug)
    except Exception as e:
        pipeline.marquer_tts(slug, "failed", str(e))
        _maj_tts(slug, statut="echec", message=str(e))
    finally:
        for temporaire in (entree, wav, timings_temporaires, mp3_temporaire):
            if os.path.exists(temporaire):
                os.remove(temporaire)


# ---------------------------------------------------------------------------
# Horodatage d'un ancien bundle anglais (SRT MacWhisper, v1.2 § 6.1)
# ---------------------------------------------------------------------------
HORODATAGES = {}  # slug -> {"statut": "en cours|ok|echec", "message"}
VERRO_HORODATAGES = threading.Lock()


def instantane_horodatages():
    with VERRO_HORODATAGES:
        return {slug: dict(etat) for slug, etat in HORODATAGES.items()}


def lancer_horodatage(slug):
    """Transcrit en SRT si besoin (MacWhisper, plusieurs minutes), puis
    re-segmente. Renvoie (lance, erreur)."""
    possible, raison = pipeline.horodatage_possible(slug)
    if not possible:
        return False, raison
    with VERRO_HORODATAGES:
        if HORODATAGES.get(slug, {}).get("statut") == "en cours":
            return False, "un horodatage est déjà en cours pour ce bundle"
        HORODATAGES[slug] = {"statut": "en cours", "message": "préparation…"}
    threading.Thread(target=_executer_horodatage, args=(slug,), daemon=True).start()
    return True, None


def _executer_horodatage(slug):
    def maj(**champs):
        with VERRO_HORODATAGES:
            HORODATAGES[slug].update(champs)
    try:
        base = os.path.join(bundles.DOSSIER_BUNDLES, slug)
        if not os.path.exists(base + ".transcript.en.srt"):
            maj(message="MacWhisper transcrit l'audio en SRT… (plusieurs minutes)")
            # Le .txt existant est sauvegardé : MacWhisper le régénère
            if os.path.exists(base + ".transcript.en.txt"):
                shutil.copyfile(base + ".transcript.en.txt", base + ".transcript.en.v1.bak.txt")
            chemin_txt, source = transcription.transcrire_macwhisper(
                base + ".mp3", base + ".transcript.en", "en")
            if not chemin_txt:
                raise RuntimeError(f"transcription SRT impossible : {source}")
        maj(message="re-segmentation depuis le SRT…")
        segments, erreur = pipeline.horodater(slug)
        if erreur:
            raise RuntimeError(erreur)
        bundles.rafraichir_meta(slug)
        maj(statut="ok", message=f"{len(segments)} segments horodatés : refaites la traduction puis l'analyse")
    except Exception as e:
        maj(statut="echec", message=str(e))


def timings_audio_atelier(slug, etat, segments):
    """Timings utilisables pour le ▶ par segment de l'atelier : ceux de
    l'audio qui sera publié (SRT pour l'original anglais, Kokoro pour une
    source française). Renvoie {"quel", "timings"} ou None."""
    source = etat.get("sourceLanguage")
    if source == "en" and pipeline.lire_infos_segments(slug)["timingSource"] == "macwhisper_srt":
        timings = [{"id": s["id"], "startMs": s.get("startMs"), "endMs": s.get("endMs")} for s in segments]
        return {"quel": "original", "timings": timings}
    if source == "fr":
        kokoro = pipeline.lire_timings_kokoro(slug, segments)
        if kokoro:
            return {"quel": "en", "timings": kokoro}
    return None


def etat_atelier():
    """Bundles + état métier calculé (etat_publication) pour l'interface."""
    resultat = []
    en_preparation = JOBS.slugs_en_preparation()
    for bundle in bundles.scanner_bundles():
        if bundle["slug"] in en_preparation:
            continue  # affiché comme job tant que l'extraction tourne
        etat = pipeline.etat_publication(
            bundle["slug"], import_en_cours=import_en_cours(bundle["slug"]))
        segments = pipeline.lire_segments(bundle["slug"]) or []
        pedagogie = pipeline.lire_pedagogie(bundle["slug"]) or {}
        meta = bundle["meta"] or {}
        resultat.append({
            "slug": bundle["slug"], "titre": bundle["titre"],
            "fichiers": bundle["fichiers"], "etat": etat,
            "niveau": meta.get("targetLevel"), "theme": meta.get("topic"),
            "segments": len(segments),
            "chunks": len(pedagogie.get("chunks", [])),
            "grammarPoints": len(pedagogie.get("grammarPoints", [])),
            "ttsVoice": meta.get("ttsVoice"),
            "autoPublish": bool(meta.get("autoPublish")),
            "createdAt": meta.get("createdAt"),
        })
    return resultat


def detail_bundle(slug):
    """Tout ce qu'il faut pour l'écran de détail d'un bundle."""
    bundle = bundles.trouver_bundle(slug)
    if not bundle:
        return None
    meta = bundle["meta"] or {}
    etat = pipeline.etat_publication(slug, import_en_cours=import_en_cours(slug))
    segments = pipeline.lire_segments(slug) or []
    source = etat["sourceLanguage"]
    cible = pipeline.langue_cible(source) if source else None
    traduits = sum(1 for s in segments if cible and (s.get(cible) or "").strip())
    pedagogie = pipeline.lire_pedagogie(slug) or {}
    hash_en = (pipeline.empreinte(pipeline.texte_complet(segments, "en"))
               if pipeline.traduction_complete(segments) else None)
    fichiers = bundle["fichiers"]
    horodatage_possible = pipeline.horodatage_possible(slug)
    transcript = ""
    if fichiers["transcript"]:
        with open(os.path.join(bundles.DOSSIER_BUNDLES, fichiers["transcript"]),
                  encoding="utf-8") as f:
            transcript = f.read()
    return {
        "slug": slug, "titre": bundle["titre"], "etat": etat,
        "meta": {cle: meta.get(cle) for cle in (
            "sourceUrl", "targetLevel", "topic", "createdAt", "processing",
            "autoPublish", "ttsVoice", "tts", "publication",
            "englishTextRevision")},
        "transcript": transcript,
        "segments": segments,
        "traduction": {
            "faits": traduits, "total": len(segments),
            "lotsTotal": len(pipeline.lots(segments, pipeline.TAILLE_LOT_TRADUCTION)),
            "sens": f"{source}→{cible}" if source else None},
        "pedagogie": {
            "chunks": pedagogie.get("chunks", []),
            "grammarPoints": pedagogie.get("grammarPoints", []),
            "lotsAnalyses": pedagogie.get("lotsAnalyses", 0)
            if pedagogie.get("englishTextHash") == hash_en else 0,
            "lotsTotal": len(pipeline.lots(segments, pipeline.TAILLE_LOT_PEDAGOGIE)),
            "existe": bool(pedagogie)},
        "audio": {"original": bool(fichiers["audio"]),
                  "en": bool(fichiers["audioEn"]),
                  "version": (meta.get("tts") or {}).get("finishedAt")},
        "horodatage": {**etat.get("horodatage", {}),
                       "segmentationVersion": etat.get("segmentationVersion"),
                       "possible": horodatage_possible[0],
                       "avertissement": horodatage_possible[1],
                       "audio": timings_audio_atelier(slug, etat, segments)},
    }


def chercher_idees(parametres):
    """Recherche YouTube (via le Worker) + présence dans l'atelier.
    Renvoie (code HTTP, corps)."""
    try:
        resultats, depuis_cache = idees.rechercher(
            parametres.get("q", ""), parametres.get("langue", "en"),
            parametres.get("duree", "moyenne"))
    except ValueError as e:
        return 400, {"erreur": str(e)}
    except RuntimeError as e:
        return 502, {"erreur": f"recherche impossible : {e}"}
    biblio = [(b["meta"] or {}).get("sourceUrl")
              for b in bundles.scanner_bundles()]
    prepa = [j["url"] for j in JOBS.instantane()
             if j["statut"] not in ("failed", "doublon")]
    return 200, {"ok": True, "cache": depuis_cache,
                 "resultats": idees.marquer_presence(resultats, biblio, prepa)}


# ---------------------------------------------------------------------------
# Serveur web
# ---------------------------------------------------------------------------
class Gestionnaire(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---- envoi de réponses -------------------------------------------
    def _envoyer(self, code, corps, type_mime="application/json; charset=utf-8"):
        donnees = corps if isinstance(corps, bytes) else json.dumps(
            corps, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(donnees)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(donnees)

    # ---- routes GET ----------------------------------------------------
    def _envoyer_audio(self, slug, quel):
        """Sert un MP3 du bundle (lecture/seek dans le navigateur) :
        uniquement <slug>.mp3 ou <slug>.audio-en.mp3, avec Range."""
        if not bundles.trouver_bundle(slug):
            self._envoyer(404, {"erreur": "bundle introuvable"})
            return
        nom = (pipeline.nom_audio_en_tts(slug) if quel == "en"
               else pipeline.nom_audio_original(slug))
        chemin = pipeline.chemin_bundle(nom)
        if not os.path.isfile(chemin):
            self._envoyer(404, {"erreur": "audio introuvable"})
            return
        taille = os.path.getsize(chemin)
        debut, fin = 0, taille - 1
        plage = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        if plage and (plage.group(1) or plage.group(2)):
            if plage.group(1):
                debut = int(plage.group(1))
                fin = int(plage.group(2)) if plage.group(2) else taille - 1
            else:
                debut = max(taille - int(plage.group(2)), 0)
            fin = min(fin, taille - 1)
            if debut > fin:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{taille}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {debut}-{fin}/{taille}")
        else:
            self.send_response(200)
        longueur = fin - debut + 1
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(longueur))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(chemin, "rb") as f:
            f.seek(debut)
            restant = longueur
            while restant > 0:
                bloc = f.read(min(65536, restant))
                if not bloc:
                    break
                try:
                    self.wfile.write(bloc)
                except (BrokenPipeError, ConnectionResetError):
                    return
                restant -= len(bloc)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        parametres = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/api/bundle":
            detail = detail_bundle(parametres.get("slug", ""))
            if detail:
                self._envoyer(200, detail)
            else:
                self._envoyer(404, {"erreur": "bundle introuvable"})
            return
        if url.path == "/api/audio":
            self._envoyer_audio(parametres.get("slug", ""),
                                parametres.get("quel", "original"))
            return
        if url.path in ("/", "/index.html"):
            try:
                with open(CHEMIN_HTML, "rb") as f:
                    page = f.read()
            except OSError:
                self._envoyer(500, {"erreur": "interface.html introuvable"})
                return
            self._envoyer(200, page, "text/html; charset=utf-8")
        elif url.path == "/api/jobs":
            self._envoyer(200, {"jobs": JOBS.instantane(),
                                "imports": instantane_imports(),
                                "tts": instantane_tts(),
                                "horodatages": instantane_horodatages()})
        elif url.path == "/api/bundles":
            self._envoyer(200, {"bundles": etat_atelier()})
        elif url.path == "/api/idees":
            self._envoyer(*chercher_idees(parametres))
        else:
            self._envoyer(404, {"erreur": "introuvable"})

    # ---- routes POST ----------------------------------------------------
    def do_POST(self):
        longueur = int(self.headers.get("Content-Length") or 0)
        try:
            donnees = json.loads(self.rfile.read(longueur).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._envoyer(400, {"erreur": "requête invalide"})
            return

        slug = str(donnees.get("slug", "")).strip()
        if self.path == "/api/atelier":
            self._atelier(donnees)
        elif self.path == "/api/jobs/masquer":
            if JOBS.masquer(str(donnees.get("jobId", ""))):
                self._envoyer(200, {"ok": True})
            else:
                self._envoyer(400, {"erreur": "job introuvable ou en cours"})
        elif self.path == "/api/jobs/relancer":
            job = JOBS.relancer(str(donnees.get("jobId", "")),
                                str(donnees.get("langueAudio", "")) or None)
            if job:
                self._envoyer(200, {"ok": True})
            else:
                self._envoyer(400, {"erreur": "job introuvable ou non échoué"})
        elif not bundles.trouver_bundle(slug):
            self._envoyer(404, {"erreur": "bundle introuvable"})
        elif self.path == "/api/prompt":
            self._prompt(slug, str(donnees.get("type", "")))
        elif self.path == "/api/coller":
            self._coller(slug, str(donnees.get("type", "")),
                         str(donnees.get("texte", "")))
        elif self.path == "/api/payload":
            payload, _etat, erreur = pipeline.payload_distant(slug)
            if erreur:
                self._envoyer(400, {"erreur": erreur})
            else:
                self._envoyer(200, {"ok": True, "payload": payload})
        elif self.path == "/api/importer":
            ok, erreur = lancer_import(slug)
            if not ok:
                self._envoyer(409, {"erreur": erreur})
            else:
                self._envoyer(200, {"ok": True})
        elif self.path == "/api/autopublish":
            meta = bundles.lire_meta(slug)
            if not meta:
                self._envoyer(404, {"erreur": "meta introuvable"})
                return
            meta["autoPublish"] = bool(donnees.get("actif"))
            bundles.ecrire_meta(slug, meta)
            self._envoyer(200, {"ok": True})
        elif self.path == "/api/horodater":
            ok, erreur = lancer_horodatage(slug)
            if not ok:
                self._envoyer(409, {"erreur": erreur})
            else:
                self._envoyer(200, {"ok": True})
        elif self.path == "/api/tts":
            voix = str(donnees.get("voix", "bf_emma"))
            if voix not in VOIX_KOKORO:
                voix = "bf_emma"
            ok, erreur = lancer_tts(slug, voix)
            if not ok:
                self._envoyer(409, {"erreur": erreur})
            else:
                self._envoyer(200, {"ok": True})
        else:
            self._envoyer(404, {"erreur": "introuvable"})

    # ---- actions --------------------------------------------------------
    def _atelier(self, donnees):
        urls = [u for u in str(donnees.get("liens", "")).split() if u]
        if not urls:
            self._envoyer(400, {"erreur": "Aucun lien fourni."})
            return
        langue = str(donnees.get("langueAudio", "auto")).lower()
        if langue not in ("auto", "fr", "en"):
            self._envoyer(400, {"erreur": "Langue source invalide (auto/fr/en)."})
            return
        niveau = str(donnees.get("niveau", "B1"))
        if niveau not in bundles.NIVEAUX:
            niveau = "B1"
        theme = str(donnees.get("theme", "")).strip()
        theme = bundles.THEMES.get(theme, theme) or None
        if theme and theme not in bundles.THEMES.values():
            theme = "other"

        crees, ignores = [], 0
        for url in urls:
            job, doublon = JOBS.ajouter(url, langue, niveau, theme,
                                        bool(donnees.get("autoPublish")))
            if doublon:
                ignores += 1
            else:
                crees.append(job.instantane())
        self._envoyer(200, {"ok": True, "jobs": crees, "ignores": ignores})

    def _prompt(self, slug, type_prompt):
        if type_prompt == "traduction":
            prompt, info, erreur = pipeline.prompt_traduction(slug)
        elif type_prompt in ("pedagogie", "chunks"):
            prompt, info, erreur = pipeline.prompt_pedagogie(slug)
        else:
            prompt, info, erreur = None, None, "type de prompt inconnu"
        if erreur:
            self._envoyer(400, {"erreur": erreur})
        else:
            self._envoyer(200, {"ok": True, "prompt": prompt, "info": info})

    def _coller(self, slug, type_resultat, texte):
        if not texte.strip():
            self._envoyer(400, {"erreur": "Texte vide."})
            return
        if type_resultat == "traduction":
            resume, erreurs = pipeline.enregistrer_traduction(slug, texte)
        elif type_resultat in ("pedagogie", "chunks"):
            resume, erreurs = pipeline.enregistrer_pedagogie(slug, texte)
        else:
            resume, erreurs = None, ["type de résultat inconnu"]
        if erreurs:
            # Rien n'a été écrit : la dernière version valide est intacte
            self._envoyer(400, {"erreur": "Résultat refusé — rien n'a été "
                                          "enregistré.",
                                "erreurs": erreurs[:30]})
        else:
            bundles.rafraichir_meta(slug)
            auto = apres_modification(slug)
            self._envoyer(200, {"ok": True, "resume": resume,
                                "autoPublication": auto})

    def log_message(self, format, *args):
        pass  # pas de journalisation des requêtes HTTP


def reprendre_au_demarrage():
    """Reconstitue l'état local après un arrêt (AC-15) : jobs rechargés,
    publications et TTS interrompus signalés, temporaires nettoyés."""
    JOBS.charger()
    for slug in bundles.lister_slugs():
        for action in pipeline.reprendre_apres_redemarrage(slug):
            print(f"   ↺ {slug} : {action}")


def main():
    # Port libre par défaut ; CONVERTISSEUR_PORT pour un port fixe
    port = int(os.environ.get("CONVERTISSEUR_PORT") or 0)
    serveur = ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire)
    port = serveur.server_address[1]
    url = f"http://127.0.0.1:{port}"
    bundles.assure_dossier()
    reprendre_au_demarrage()
    print("🎓 Atelier English Fluency")
    print(f"   Interface   : {url}")
    print(f"   Bundles     : {bundles.DOSSIER_BUNDLES}")
    print("   Pour arrêter : Ctrl+C dans cette fenêtre (ou fermez le Terminal).")

    # Ouvre le navigateur (sauf en mode test)
    if not os.environ.get("CONVERTISSEUR_SANS_NAVIGATEUR"):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt de l'atelier. À bientôt !")
    finally:
        serveur.server_close()


if __name__ == "__main__":
    main()
