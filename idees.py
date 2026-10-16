# -*- coding: utf-8 -*-
"""Idées de contenus : recherche de vidéos YouTube via le Worker.

Le Worker expose GET /youtube/search et GET /youtube/videos (proxys vers
l'API YouTube Data v3, clés en rotation). Un appel « search » coûte 100
unités de quota sur 10 000 par jour et par clé : les recherches
identiques sont gardées en mémoire une heure.
"""

import json
import re
import threading
import time
import urllib.parse

import bundles

DUREE_CACHE = 3600          # secondes
MAX_RESULTATS = 15
DUREES = {"courte": "short", "moyenne": "medium", "longue": "long",
          "toutes": "any"}
LANGUES = ("en", "fr")

_CACHE = {}                 # clé de recherche -> (horodatage, résultats)
_VERROU = threading.Lock()


def vider_cache():
    with _VERROU:
        _CACHE.clear()


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def id_video(url):
    """Identifiant YouTube (11 caractères) d'une URL, sinon None."""
    url = str(url or "").strip()
    morceaux = urllib.parse.urlsplit(url)
    hote = morceaux.netloc.lower()
    if hote.endswith("youtu.be"):
        candidat = morceaux.path.lstrip("/").split("/")[0]
    elif "youtube" in hote:
        parametres = urllib.parse.parse_qs(morceaux.query)
        candidat = (parametres.get("v") or [""])[0]
        if not candidat:
            chemin = re.match(r"/(?:shorts|embed|live|v)/([^/?#]+)",
                              morceaux.path)
            candidat = chemin.group(1) if chemin else ""
    else:
        return None
    return candidat if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidat) else None


def url_video(identifiant):
    return f"https://www.youtube.com/watch?v={identifiant}"


def secondes_iso(duree):
    """'PT1H2M3S' -> 3723. Renvoie None si illisible."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
                     str(duree or ""))
    if not m or not any(m.groups()):
        return None
    j, h, mi, s = (int(x or 0) for x in m.groups())
    return ((j * 24 + h) * 60 + mi) * 60 + s


def _miniature(snippet):
    vignettes = snippet.get("thumbnails") or {}
    for taille in ("medium", "high", "default"):
        if (vignettes.get(taille) or {}).get("url"):
            return vignettes[taille]["url"]
    return None


# ---------------------------------------------------------------------------
# Appels au Worker
# ---------------------------------------------------------------------------
def _appel(config, chemin, parametres):
    url = (f"{config['workerUrl']}{chemin}?"
           + urllib.parse.urlencode(parametres))
    corps = bundles._requete_worker(
        url, entetes={"Authorization": f"Bearer {config['apiSecret']}"},
        timeout=20)
    try:
        return json.loads(corps)
    except ValueError:
        raise RuntimeError("réponse du Worker illisible")


def _interroger(q, langue, duree, maximum):
    config, erreur = bundles.charger_config_import()
    if erreur:
        raise RuntimeError(erreur)
    recherche = _appel(config, "/youtube/search", {
        "part": "snippet", "type": "video", "q": q,
        "relevanceLanguage": langue, "videoDuration": DUREES[duree],
        "videoCaption": "any", "maxResults": maximum,
        "safeSearch": "moderate",
    })
    ids = [((e.get("id") or {}).get("videoId"))
           for e in recherche.get("items") or []]
    ids = [i for i in ids if i]
    if not ids:
        return []
    videos = _appel(config, "/youtube/videos", {
        "part": "contentDetails,snippet,statistics", "id": ",".join(ids),
        "maxResults": len(ids),
    })
    par_id = {v.get("id"): v for v in videos.get("items") or []}
    resultats = []
    for identifiant in ids:          # garde l'ordre de pertinence
        video = par_id.get(identifiant)
        if not video:
            continue                 # supprimée ou privée entre-temps
        snippet = video.get("snippet") or {}
        stats = video.get("statistics") or {}
        langue_video = (snippet.get("defaultAudioLanguage")
                        or snippet.get("defaultLanguage") or "")[:2].lower()
        vues = stats.get("viewCount")
        resultats.append({
            "id": identifiant,
            "url": url_video(identifiant),
            "titre": snippet.get("title") or identifiant,
            "chaine": snippet.get("channelTitle") or "",
            "miniature": _miniature(snippet),
            "duree": secondes_iso(
                (video.get("contentDetails") or {}).get("duration")),
            "date": snippet.get("publishedAt"),
            "langue": langue_video or None,
            "vues": int(vues) if str(vues or "").isdigit() else None,
        })
    return resultats


def rechercher(q, langue="en", duree="moyenne", maximum=12,
               maintenant=time.time):
    """Renvoie (résultats, depuis_cache). Lève ValueError si les
    paramètres sont invalides, RuntimeError si le Worker échoue."""
    q = " ".join(str(q or "").split())[:120]
    if not q:
        raise ValueError("recherche vide")
    if langue not in LANGUES:
        raise ValueError("langue invalide (en/fr)")
    if duree not in DUREES:
        raise ValueError("durée invalide (courte/moyenne/longue/toutes)")
    maximum = max(1, min(int(maximum), MAX_RESULTATS))
    cle = (q.lower(), langue, duree, maximum)
    with _VERROU:
        entree = _CACHE.get(cle)
        if entree and maintenant() - entree[0] < DUREE_CACHE:
            return [dict(r) for r in entree[1]], True
    resultats = _interroger(q, langue, duree, maximum)
    with _VERROU:
        for k in [k for k, (t, _r) in _CACHE.items()
                  if maintenant() - t >= DUREE_CACHE]:
            del _CACHE[k]
        _CACHE[cle] = (maintenant(), resultats)
    return [dict(r) for r in resultats], False


def marquer_presence(resultats, urls_bibliotheque, urls_preparation):
    """Ajoute à chaque résultat « presence » : 'bibliotheque',
    'preparation' ou None, en comparant les identifiants de vidéo."""
    biblio = {id_video(u) for u in urls_bibliotheque} - {None}
    prepa = {id_video(u) for u in urls_preparation} - {None}
    for r in resultats:
        r["presence"] = ("bibliotheque" if r["id"] in biblio
                         else "preparation" if r["id"] in prepa else None)
    return resultats
