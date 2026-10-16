# -*- coding: utf-8 -*-
"""Bundles de préparation pour English Fluency — voir IMPORT_BUNDLES_SPEC.md.

Un contenu = un bundle : tous les fichiers d'un contenu partagent le même
slug et vivent dans fileToImport/ :

    <slug>.mp3                     audio original (FR ou EN), jamais écrasé
    <slug>.audio-en.mp3            audio anglais Kokoro (source FR)
    <slug>.transcript.<langue>.txt transcription de la source
    <slug>.translation.<langue>.txt traduction intégrale (copie lisible)
    <slug>.segments.json           segments EN/FR appariés
    <slug>.pedagogy.json           chunks + points de grammaire
    <slug>.meta.json               manifeste local (obligatoire)

La logique métier (prompts, validation, canPublish, payload) vit dans
pipeline.py ; ce module gère les fichiers et la connexion au Worker.
"""

import datetime
import json
import os
import re
import tempfile
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

VERRO = threading.Lock()

# ATELIER_DOSSIER_BUNDLES permet de travailler sur un autre dossier
# (démonstration, essais) sans toucher à fileToImport/.
DOSSIER_BUNDLES = os.environ.get("ATELIER_DOSSIER_BUNDLES") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fileToImport")
CHEMIN_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config_import.json")

# Thèmes : libellé affiché -> valeur écrite dans le meta
THEMES = {
    "Travail": "work",
    "Quotidien": "daily",
    "Culture": "culture",
    "Tech": "tech",
    "Voyage": "travel",
    "Autre": "other",
}

NIVEAUX = ("A2", "B1", "B2")


# ---------------------------------------------------------------------------
# Slug
# ---------------------------------------------------------------------------
def slugifier(titre):
    """Transforme un titre en slug propre : minuscules, sans accent,
    mots séparés par des tirets, 60 caractères maximum."""
    texte = unicodedata.normalize("NFKD", str(titre))
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[^a-zA-Z0-9]+", "-", texte).strip("-").lower()
    texte = re.sub(r"-{2,}", "-", texte)
    return (texte[:60].rstrip("-")) or "contenu"


def slug_disponible(slug, url=None):
    """Renvoie un slug unique dans fileToImport/.

    Si un bundle existe déjà avec la même URL, il est considéré comme
    doublon (slug vide renvoyé). Sinon, un suffixe -2, -3… est ajouté."""
    assure_dossier()
    if url:
        for nom in os.listdir(DOSSIER_BUNDLES):
            if not nom.endswith(".meta.json"):
                continue
            try:
                with open(os.path.join(DOSSIER_BUNDLES, nom),
                          encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("sourceUrl") == url:
                    return None, meta.get("id")
            except (OSError, ValueError):
                continue
    candidat = slug
    compteur = 2
    while any(nom.startswith(candidat + ".")
              for nom in os.listdir(DOSSIER_BUNDLES)):
        candidat = f"{slug}-{compteur}"
        compteur += 1
    return candidat, None


def assure_dossier():
    os.makedirs(DOSSIER_BUNDLES, exist_ok=True)
    return DOSSIER_BUNDLES


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------
def maintenant():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def construire_meta(slug, titre, url, langue_source, langue_transcript,
                    niveau, theme=None, statut="incomplet",
                    auto_publier=False):
    """Meta v2 (cahier des charges §7.2). audioLanguage est conservé :
    c'est la langue de l'audio ORIGINAL, lue par les anciens outils."""
    meta = {
        "schemaVersion": 2,
        "id": slug,
        "title": titre,
        "sourceType": "youtube",
        "sourceUrl": url,
        "sourceLanguage": langue_source,
        "learningLanguage": "en",
        "targetLocale": "en-GB",
        "audioLanguage": langue_source,
        "transcriptLanguage": langue_transcript,
        "targetLevel": niveau,
        "accent": "en-GB",
        "contentKind": "youtube_audio",
        "rights": "personal_use",
        "status": statut,
        "translationValidated": False,
        "pedagogyValidated": False,
        "englishTextRevision": 0,
        "autoPublish": bool(auto_publier),
        "publication": {"status": None, "remoteId": None,
                        "remoteVersion": None, "publishedAt": None},
        "createdAt": maintenant(),
    }
    if theme:
        meta["topic"] = theme
    return meta


def ecrire_meta(slug, meta):
    """Écriture atomique (fichier temporaire caché puis renommage)."""
    chemin = os.path.join(DOSSIER_BUNDLES, f"{slug}.meta.json")
    descripteur, temporaire = tempfile.mkstemp(dir=DOSSIER_BUNDLES,
                                               prefix=".tmp-")
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.replace(temporaire, chemin)
    except BaseException:
        if os.path.exists(temporaire):
            os.remove(temporaire)
        raise
    return chemin


def lire_meta(slug):
    chemin = os.path.join(DOSSIER_BUNDLES, f"{slug}.meta.json")
    if not os.path.exists(chemin):
        return None
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def decrire_fichiers(slug):
    """Inventorie les fichiers d'un bundle (nommage à plat). Renvoie un
    dict : audio (original), audioEn (Kokoro), transcript (+langue),
    translation (+langue), adapted (ancien format), segments, pedagogy,
    meta."""
    description = {"audio": None, "audioEn": None, "transcript": None,
                   "langueTranscript": None, "transcriptSrt": None,
                   "timingsEn": None, "source": None, "adapted": None,
                   "niveauAdapted": None, "translation": None,
                   "langueTranslation": None, "segments": None,
                   "pedagogy": None, "meta": None}
    assure_dossier()
    for nom in os.listdir(DOSSIER_BUNDLES):
        if not nom.startswith(slug + "."):
            continue
        if nom == f"{slug}.mp3":
            description["audio"] = nom
        elif nom == f"{slug}.audio-en.mp3":
            description["audioEn"] = nom
        elif nom == f"{slug}.meta.json":
            description["meta"] = nom
        elif nom == f"{slug}.segments.json":
            description["segments"] = nom
        elif nom == f"{slug}.pedagogy.json":
            description["pedagogy"] = nom
        elif nom == f"{slug}.audio-en.timings.json":
            description["timingsEn"] = nom
        else:
            m = re.match(rf"^{re.escape(slug)}\.transcript\.(\w+)\.txt$", nom)
            if m:
                description["transcript"] = nom
                description["langueTranscript"] = m.group(1)
                continue
            if re.match(rf"^{re.escape(slug)}\.source\.(\w+)\.(txt|md)$", nom):
                description["source"] = nom
                continue
            if re.match(rf"^{re.escape(slug)}\.transcript\.(\w+)\.srt$", nom):
                description["transcriptSrt"] = nom
                continue
            m = re.match(rf"^{re.escape(slug)}\.adapted\.en-(\w+)\.txt$", nom)
            if m:
                description["adapted"] = nom
                description["niveauAdapted"] = m.group(1)
                continue
            m = re.match(rf"^{re.escape(slug)}\.translation\.(\w+)\.txt$", nom)
            if m:
                description["translation"] = nom
                description["langueTranslation"] = m.group(1)
    return description


def rafraichir_meta(slug):
    """Recalcule availableFiles puis réécrit le meta. Le statut métier
    est calculé par pipeline.etat_publication, pas ici."""
    meta = lire_meta(slug)
    if not meta:
        return None
    description = decrire_fichiers(slug)
    cles = {"audio": "audio", "audioEn": "audioEn",
            "transcript": "transcript", "transcriptSrt": "transcriptSrt",
            "timingsEn": "timingsEn", "source": "sourceText",
            "adapted": "adaptedText",
            "translation": "translation", "segments": "segments",
            "pedagogy": "pedagogy"}
    meta["availableFiles"] = {cle_meta: description[cle]
                              for cle, cle_meta in cles.items()
                              if description[cle]}
    ecrire_meta(slug, meta)
    return meta


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
def lister_slugs():
    assure_dossier()
    return sorted({nom.split(".", 1)[0] for nom in os.listdir(DOSSIER_BUNDLES)
                   if not nom.startswith((".", "_"))})


def scanner_bundles():
    """Liste les bundles de fileToImport/ (fichiers + meta bruts)."""
    resultat = []
    for slug in lister_slugs():
        description = decrire_fichiers(slug)
        meta = lire_meta(slug) if description["meta"] else None
        resultat.append({"slug": slug,
                         "titre": (meta or {}).get("title", slug),
                         "meta": meta, "fichiers": description})
    return resultat


def trouver_bundle(slug):
    if not slug or slug not in lister_slugs():
        return None
    description = decrire_fichiers(slug)
    meta = lire_meta(slug) if description["meta"] else None
    return {"slug": slug, "titre": (meta or {}).get("title", slug),
            "meta": meta, "fichiers": description}


# ---------------------------------------------------------------------------
# Import vers le Worker (spec §9) — upload R2 + POST /content
# ---------------------------------------------------------------------------
def charger_config_import():
    """Lit config_import.json. Renvoie (config dict, None) ou (None, erreur)."""
    try:
        with open(CHEMIN_CONFIG, encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        return None, ("config_import.json introuvable — créez-le avec "
                      "workerUrl et apiSecret (voir README)")
    except ValueError:
        return None, "config_import.json invalide (JSON malformé)"
    if not config.get("workerUrl") or not config.get("apiSecret"):
        return None, "config_import.json incomplet (workerUrl, apiSecret)"
    config["workerUrl"] = str(config["workerUrl"]).rstrip("/")
    config.setdefault("profileId", "default")
    return config, None


def _requete_worker(url, donnees=None, entetes=None, methode="GET", timeout=60):
    """POST/GET vers le worker. Renvoie le corps décodé ou lève RuntimeError
    avec un message lisible."""
    # Cloudflare bloque l'User-Agent par défaut de Python (erreur 1010).
    entetes = dict(entetes or {})
    entetes.setdefault("User-Agent",
                       "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36 convertisseur-atelier/1.0")
    requete = urllib.request.Request(url, data=donnees, headers=entetes,
                                     method=methode)
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            return reponse.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace").strip()
        raise RuntimeError(f"HTTP {e.code} — {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"worker injoignable : {e.reason}")
