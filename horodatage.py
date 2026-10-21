# -*- coding: utf-8 -*-
"""Horodatage des segments (LOT 1, écoute active v1.2 § 6.1 et § 6.4).

Fonctions pures, sans MacWhisper ni Kokoro :
- lecture d'un SRT MacWhisper et texte brut dérivé ;
- phrases horodatées d'une piste YouTube automatique ;
- regroupement des répliques en segments (~220 caractères, sans jamais
  couper une réplique) avec startMs / endMs ;
- contrôles des timings avant publication ;
- débit (mots par minute) par segment et global.
"""

import html
import re

SEGMENT_CIBLE = 220             # caractères visés par segment (comme pipeline.py)
CHEVAUCHEMENT_MAX_MS = 200      # tolérance entre deux segments consécutifs
DEPASSEMENT_FIN_MAX_MS = 500    # fin du dernier segment <= durée + 500 ms

TIMING_SRT = "macwhisper_srt"
TIMING_KOKORO = "kokoro"

_HORODATAGE = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")


def _ms(h, m, s, fraction):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(fraction.ljust(3, "0")[:3])


def lire_srt(texte):
    """Répliques d'un SRT : [{"startMs", "endMs", "text"}], dans l'ordre du
    fichier. Les blocs sans horodatage ou sans texte sont ignorés."""
    repliques = []
    propre = (texte or "").lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    for bloc in re.split(r"\n\s*\n", propre):
        lignes = [ligne.strip() for ligne in bloc.strip().split("\n") if ligne.strip()]
        for i, ligne in enumerate(lignes):
            m = _HORODATAGE.search(ligne)
            if not m:
                continue
            contenu = " ".join(" ".join(lignes[i + 1:]).split())
            if contenu:
                repliques.append({"startMs": _ms(*m.groups()[:4]),
                                  "endMs": _ms(*m.groups()[4:]),
                                  "text": contenu})
            break
    return repliques


_ENTETE_VTT = re.compile(r"^(\d+):(\d{2}):(\d{2})\.(\d{3})\s+-->\s+(\d+):(\d{2}):(\d{2})\.(\d{3})")
_MOT_HORODATE = re.compile(r"<(\d+):(\d{2}):(\d{2})\.(\d{3})>")
_FIN_DE_PHRASE = re.compile(r"[.!?…][\"'”»)]*$")
PHRASE_MAX = 400  # une phrase sans ponctuation est coupée au-delà


def lire_vtt_automatique(texte):
    """Phrases horodatées d'une piste YouTube automatique (.vtt).

    Chaque cue répète la ligne précédente en « écho » : seule sa dernière
    ligne est nouvelle, avec l'heure de chaque mot (<hh:mm:ss.mmm>). Les
    mots sont recollés puis recoupés en phrases sur la ponctuation et sur
    les changements d'intervenant (« >> »). Les annotations entre crochets
    ([music]) sont retirées. Une phrase finit avec la cue de son dernier
    mot : les silences et musiques ne restent pas surlignés.
    Renvoie [{"startMs", "endMs", "text"}]."""
    mots = []
    lignes = html.unescape(texte or "").lstrip("﻿").replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lignes):
        entete = _ENTETE_VTT.match(lignes[i].strip())
        i += 1
        if not entete:
            continue
        debut, fin = _ms(*entete.groups()[:4]), _ms(*entete.groups()[4:])
        contenu = []
        while i < len(lignes) and lignes[i] != "":
            contenu.append(lignes[i])
            i += 1
        # Les cues de transition (10 ms) finissent par une ligne blanche : rien de neuf.
        if not contenu or not contenu[-1].strip():
            continue
        morceaux = _MOT_HORODATE.split(contenu[-1])
        instants = [debut] + [_ms(*morceaux[k:k + 4]) for k in range(1, len(morceaux), 5)]
        for instant, bout in zip(instants, morceaux[0::5]):
            for mot in re.sub(r"<[^>]*>", "", bout).split():
                mots.append((instant, mot, fin))

    phrases, courante = [], []

    def clore():
        if courante:
            phrases.append({"startMs": courante[0][0], "endMs": courante[-1][2],
                            "text": " ".join(m for _, m, _ in courante)})
            courante.clear()

    entre_crochets = False
    for instant, mot, fin in mots:
        if mot.startswith("["):
            entre_crochets = True
        if entre_crochets:
            entre_crochets = not mot.endswith("]")
            continue
        if mot == ">>":
            clore()
            continue
        if courante and sum(len(m) + 1 for _, m, _ in courante) + len(mot) > PHRASE_MAX:
            clore()
        courante.append((instant, mot, fin))
        if _FIN_DE_PHRASE.search(mot):
            clore()
    clore()

    # Débuts strictement croissants : une phrase qui commence au même instant rejoint la précédente.
    resultat = []
    for phrase in phrases:
        if resultat and phrase["startMs"] <= resultat[-1]["startMs"]:
            resultat[-1]["text"] += " " + phrase["text"]
            resultat[-1]["endMs"] = phrase["endMs"]
        else:
            resultat.append(phrase)
    for courant, suivant in zip(resultat, resultat[1:]):
        courant["endMs"] = min(courant["endMs"], suivant["startMs"])
    for phrase in resultat:
        phrase["endMs"] = max(phrase["endMs"], phrase["startMs"] + 1)
    return resultat


def srt_vers_texte(repliques):
    """Texte brut dérivé du SRT (ancien pipeline .txt) : une réplique par
    ligne, sans horodatage."""
    return "\n".join(r["text"] for r in repliques)


def regrouper_repliques(repliques, cible=SEGMENT_CIBLE):
    """Regroupe des répliques consécutives en segments d'environ `cible`
    caractères. Une réplique n'est jamais coupée ni déplacée ; une
    réplique plus longue que la cible forme un segment à elle seule.
    Renvoie [{"text", "startMs", "endMs"}]."""
    segments, courant = [], None
    for replique in repliques:
        if courant and len(courant["text"]) + 1 + len(replique["text"]) > cible:
            segments.append(courant)
            courant = None
        if courant is None:
            courant = dict(replique)
        else:
            courant["text"] = f"{courant['text']} {replique['text']}"
            courant["endMs"] = replique["endMs"]
    if courant:
        segments.append(courant)
    return segments


def _nombre(valeur):
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


def verifier_timings(segments, duree_ms=None):
    """Contrôles avant publication (v1.2 § 6.1). Renvoie (statut, raisons)
    avec statut "valid", "invalid" ou "absent" (aucun timing).
    Un horodatage invalide n'empêche pas la publication : il désactive
    seulement l'écoute active."""
    if not segments or all(s.get("startMs") is None and s.get("endMs") is None
                           for s in segments):
        return "absent", []
    raisons = []
    precedent = None
    for s in segments:
        debut, fin = s.get("startMs"), s.get("endMs")
        if not (_nombre(debut) and _nombre(fin)):
            raisons.append(f"{s.get('id')} : timing manquant")
            continue
        if fin < debut:
            raisons.append(f"{s.get('id')} : fin avant le début")
        if precedent:
            if debut < precedent["startMs"]:
                raisons.append(f"{s.get('id')} : début avant celui de {precedent['id']}")
            elif precedent["endMs"] - debut > CHEVAUCHEMENT_MAX_MS:
                raisons.append(f"{s.get('id')} : chevauche {precedent['id']} de "
                               f"{precedent['endMs'] - debut} ms")
        precedent = {"id": s.get("id"), "startMs": debut, "endMs": fin}
    if duree_ms is not None and precedent and precedent["endMs"] > duree_ms + DEPASSEMENT_FIN_MAX_MS:
        raisons.append(f"le dernier segment finit après l'audio "
                       f"({precedent['endMs']} ms > {round(duree_ms)} ms)")
    return ("invalid" if raisons else "valid"), raisons


def compter_mots(texte):
    return len(re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)*", texte or ""))


def mots_par_minute(texte, debut_ms, fin_ms):
    """Débit d'un passage, arrondi ; None sans durée exploitable. C'est un
    indice parmi d'autres (v1.2 § 6.4), pas une mesure de difficulté."""
    if not (_nombre(debut_ms) and _nombre(fin_ms)) or fin_ms - debut_ms < 500:
        return None
    mots = compter_mots(texte)
    return round(mots / ((fin_ms - debut_ms) / 60000)) if mots else None


def debit_global(segments, langue="en"):
    """Mots par minute sur l'ensemble des segments horodatés (temps de
    parole : silences entre segments exclus)."""
    mots, duree = 0, 0
    for s in segments or []:
        if _nombre(s.get("startMs")) and _nombre(s.get("endMs")) and s["endMs"] > s["startMs"]:
            mots += compter_mots(s.get(langue))
            duree += s["endMs"] - s["startMs"]
    return round(mots / (duree / 60000)) if mots and duree >= 500 else None
