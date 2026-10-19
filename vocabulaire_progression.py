# -*- coding: utf-8 -*-
"""Lecture compacte des mots déjà connus dans le profil SRS du Worker."""

import json
import threading
import time
import urllib.parse

import bundles


DUREE_CACHE = 300
VERROU = threading.RLock()
_cache = {"chargeA": 0.0, "profileId": "", "ids": set()}


def vider_cache():
    with VERROU:
        _cache.update(chargeA=0.0, profileId="", ids=set())


def charger_ids_connus(force=False):
    """Renvoie les identifiants dont le statut SRS est `known`."""
    config, erreur = bundles.charger_config_import()
    if erreur:
        raise RuntimeError(erreur)
    profil = str(config.get("profileId") or "default")
    with VERROU:
        encore_valide = time.monotonic() - _cache["chargeA"] < DUREE_CACHE
        if not force and _cache["profileId"] == profil and encore_valide:
            return set(_cache["ids"])

    parametres = urllib.parse.urlencode({"profileId": profil})
    corps = bundles._requete_worker(
        f"{config['workerUrl']}/srs/progress?{parametres}",
        entetes={"Authorization": f"Bearer {config['apiSecret']}"})
    try:
        objet = json.loads(corps)
    except ValueError as erreur_json:
        raise RuntimeError(f"réponse /srs/progress invalide : {erreur_json}") from erreur_json
    mots = objet.get("words") if isinstance(objet, dict) else None
    if not isinstance(mots, list):
        raise RuntimeError("réponse /srs/progress invalide : liste words absente")
    ids = {str(mot.get("id")) for mot in mots
           if mot.get("id") is not None and mot.get("status") == "known"}
    with VERROU:
        _cache.update(chargeA=time.monotonic(), profileId=profil, ids=ids)
    return set(ids)
