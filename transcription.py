# -*- coding: utf-8 -*-
"""Transcription automatique pour le convertisseur YouTube → MP3.

Deux sources, dans l'ordre de préférence :
1. les sous-titres de la vidéo YouTube (manuels, sinon automatiques) —
   instantané, la vidéo est déjà transcrite par YouTube ;
2. MacWhisper (https://macwhisper.app) et son outil en ligne de commande
   `mw`, qui transcrit l'audio localement avec Whisper — utilisé quand la
   vidéo n'a aucun sous-titre (ou sur demande explicite).

L'atelier English Fluency (convertisseur_web.py) n'utilise que
MacWhisper : la transcription y est toujours faite localement.
"""

import html
import os
import re
import subprocess
import threading

CHEMIN_MW = "/Applications/MacWhisper.app/Contents/MacOS/mw"
LIBELLES_MODES = {
    "Auto (rapide)": "auto",          # sous-titres YouTube, sinon MacWhisper
    "MacWhisper (précis)": "whisper", # toujours transcrire localement
    "Aucune": "aucune",
}

# Un seul Whisper à la fois (très gourmand sur Mac Intel)
VERRO_WHISPER = threading.Lock()


def trouver_macwhisper():
    """Renvoie le chemin de l'outil `mw`, ou None s'il est absent."""
    if os.path.exists(CHEMIN_MW):
        return CHEMIN_MW
    # Installation « utilisateur » de MacWhisper
    autre = os.path.expanduser("~/Applications/MacWhisper.app/Contents/MacOS/mw")
    return autre if os.path.exists(autre) else None


# ---------------------------------------------------------------------------
# Sous-titres YouTube → texte propre
# ---------------------------------------------------------------------------
def vtt_vers_texte(chemin_vtt):
    """Convertit un fichier .vtt (sous-titres YouTube) en texte lisible.

    Sous-titres automatiques : chaque fragment neuf est répété en « écho »
    (cue très court sans balise) et la ligne balisée d'un cue contient le
    texte réellement nouveau. On ne conserve donc que les lignes portant
    un horodatage interne (<hh:mm:ss.sss>), sans balises. Pour les
    fichiers à cues mono-lignes (ancien format), on prend le premier cue
    complet puis uniquement les ajouts <c>.
    """
    with open(chemin_vtt, encoding="utf-8", errors="replace") as f:
        lignes = f.read().splitlines()

    # Découpe en cues en conservant la structure des lignes internes
    cues, courant = [], []
    for ligne in lignes:
        ligne = ligne.strip()
        if not ligne:
            if courant:
                cues.append(courant)
                courant = []
            continue
        if ligne.startswith(("WEBVTT", "Kind:", "Language:", "NOTE",
                             "STYLE", "REGION")):
            continue
        if "-->" in ligne or ligne.isdigit():  # minutage ou identifiant
            continue
        courant.append(ligne)
    if courant:
        cues.append(courant)

    motif_horodatage = re.compile(r"<\d{2}:\d{2}:\d{2}")
    balises_internes = any(motif_horodatage.search(l)
                           for cue in cues for l in cue)
    cues_multi_lignes = any(len(cue) > 1 for cue in cues)

    def propre(texte):
        return html.unescape(re.sub(r"<[^>]+>", "", texte)).strip()

    if balises_internes and cues_multi_lignes:
        # Sous-titres automatiques : ne garder que les lignes balisées
        # (le nouveau texte) ; les « échos » non balisés sont ignorés.
        morceaux = [propre(l) for cue in cues for l in cue
                    if motif_horodatage.search(l)]
    elif any("<c" in l for cue in cues for l in cue):
        # Ancien format automatique mono-ligne : fenêtre glissante
        morceaux = []
        for index, cue in enumerate(cues):
            ajouts = re.findall(r"<c[^>]*>(.*?)</c>", " ".join(cue))
            if index == 0 or not ajouts:
                texte = propre(" ".join(cue))
                if texte:
                    morceaux.append(texte)
            else:
                for ajout in ajouts:
                    ajout = propre(ajout)
                    if ajout:
                        morceaux.append(ajout)
    else:
        # Sous-titres manuels : cues distincts, dédoublonnage consécutif
        morceaux, precedent = [], None
        for cue in cues:
            texte = propre(" ".join(cue))
            if texte and texte != precedent:
                morceaux.append(texte)
            precedent = texte

    texte = re.sub(r"\s+", " ", " ".join(morceaux)).strip()
    # Une ligne tous les ~15 mots pour un fichier agréable à lire
    mots = texte.split(" ")
    return "\n".join(
        " ".join(mots[i:i + 15]) for i in range(0, len(mots), 15))


def choisir_sous_titres(url, langues_preferees=None):
    """Choisit la meilleure piste de sous-titres : manuelle de préférence,
    sinon automatique. Renvoie (langue, automatiques) ou (None, raison)."""
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                           "noprogress": True, "noplaylist": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return None, "informations de la vidéo indisponibles"

    manuelles = {l for l in (info.get("subtitles") or {}) if l != "live_chat"}
    auto = {l for l in (info.get("automatic_captions") or {})
            if l != "live_chat"}
    langue_video = (info.get("language")
                    or info.get("detected_language") or "")[:2]
    preferences = [l for l in (langues_preferees or []) if l]
    preferences += [l for l in (langue_video, "fr", "en")
                    if l and l not in preferences]

    def choisir(source):
        for langue in preferences:
            if langue in source:
                return langue
        return sorted(source)[0] if source else None

    langue_choisie = choisir(manuelles)
    if langue_choisie:
        return langue_choisie, False
    langue_choisie = choisir(auto)
    if langue_choisie:
        return langue_choisie, True
    return None, "la vidéo n'a aucun sous-titre"


def telecharger_sous_titres(url, base_sans_extension, langue, automatiques):
    """Télécharge la piste choisie en .vtt/.srt à côté du bundle.
    Renvoie le chemin du fichier téléchargé, ou None."""
    import yt_dlp

    options = {
        "skip_download": True,
        "writesubtitles": not automatiques,
        "writeautomaticsub": automatiques,
        "subtitleslangs": [langue],
        "subtitlesformat": "vtt/srt/best",
        "outtmpl": base_sans_extension + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "overwrites": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])
    for candidat in (f"{base_sans_extension}.{langue}.vtt",
                     f"{base_sans_extension}.{langue}.srt"):
        if os.path.exists(candidat):
            return candidat
    return None


def sous_titres_youtube(url, base_sans_extension):
    """Télécharge les sous-titres YouTube et écrit un .txt à côté du MP3.

    `base_sans_extension` : chemin du MP3 sans extension (le .txt aura le
    même nom). Renvoie (chemin_txt, source) ou (None, raison).
    """
    langue, resultat = choisir_sous_titres(url)
    if not langue:
        return None, resultat
    automatiques = resultat

    chemin_vtt = telecharger_sous_titres(url, base_sans_extension,
                                         langue, automatiques)
    if not chemin_vtt:
        return None, "téléchargement des sous-titres impossible"

    texte = vtt_vers_texte(chemin_vtt)
    os.remove(chemin_vtt)
    if not texte.strip():
        return None, "sous-titres vides"
    chemin_txt = base_sans_extension + ".txt"
    with open(chemin_txt, "w", encoding="utf-8") as f:
        f.write(texte + "\n")
    origine = "automatiques" if automatiques else "manuels"
    return chemin_txt, f"sous-titres YouTube ({origine}, {langue})"


# ---------------------------------------------------------------------------
# MacWhisper (transcription locale)
# ---------------------------------------------------------------------------
def transcrire_macwhisper(chemin_audio, base_sans_extension, langue=None):
    """Transcrit l'audio avec MacWhisper et écrit un .txt.
    Renvoie (chemin_txt, source) ou (None, raison)."""
    mw = trouver_macwhisper()
    if not mw:
        return None, ("MacWhisper est introuvable — installez-le depuis "
                      "macwhisper.app si vous voulez la transcription locale")
    chemin_txt = base_sans_extension + ".txt"
    commande = [
        mw, "transcribe",
        "--language", langue if langue else "auto",
        "--format", "txt",
        "--output", chemin_txt,
        "--overwrite",
        chemin_audio,
    ]
    try:
        with VERRO_WHISPER:
            resultat = subprocess.run(commande, capture_output=True,
                                      text=True,
                                      timeout=7200)  # 2 h max pour les longs audio
    except subprocess.TimeoutExpired:
        return None, "transcription MacWhisper interrompue (trop longue)"
    if resultat.returncode != 0 or not os.path.exists(chemin_txt):
        detail = (resultat.stderr or resultat.stdout or "").strip()
        derniere = detail.splitlines()[-1] if detail else "échec MacWhisper"
        return None, derniere
    return chemin_txt, "MacWhisper (transcription locale)"


# ---------------------------------------------------------------------------
# Point d'entrée utilisé par les deux applications
# ---------------------------------------------------------------------------
def produire_transcription(url, chemin_mp3, mode, langue=None, signal=None):
    """Produit le .txt à côté du MP3 selon le mode choisi.

    mode : "auto" (sous-titres sinon MacWhisper), "whisper" (toujours
    MacWhisper) ou "aucune". `signal(etape)` facultatif pour informer
    l'interface de l'étape en cours.
    Renvoie (chemin_txt ou None, source ou message explicatif).
    """
    if mode not in ("auto", "whisper"):
        return None, None
    base = os.path.splitext(chemin_mp3)[0]

    if mode == "auto" and url:
        if signal:
            signal("Transcription : recherche des sous-titres YouTube…")
        chemin_txt, source = sous_titres_youtube(url, base)
        if chemin_txt:
            return chemin_txt, source

    if signal:
        signal("Transcription MacWhisper… (peut prendre quelques minutes)")
    return transcrire_macwhisper(chemin_mp3, base, langue)
