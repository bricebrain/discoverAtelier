# -*- coding: utf-8 -*-
"""Façade métier de l'atelier d'enrichissement du vocabulaire."""

import json
import threading
import time
import urllib.parse

import bundles
import ollama_vocabulaire
import vocabulaire_lots
import vocabulaire_progression
import vocabulaire_suppression


TAILLE_PAGE_WORKER = 1000
DUREE_CACHE = 300
VERROU = threading.RLock()
_cache = {"chargeA": 0.0, "mots": []}


def vider_cache():
    with VERROU:
        _cache.update(chargeA=0.0, mots=[])
    vocabulaire_progression.vider_cache()


def _lire_page(config, offset):
    parametres = urllib.parse.urlencode({"limit": TAILLE_PAGE_WORKER, "offset": offset})
    corps = bundles._requete_worker(
        f"{config['workerUrl']}/words?{parametres}",
        entetes={"Authorization": f"Bearer {config['apiSecret']}"})
    try:
        objet = json.loads(corps)
    except ValueError as erreur:
        raise RuntimeError(f"réponse /words invalide : {erreur}") from erreur
    mots = objet.get("words") if isinstance(objet, dict) else None
    if not isinstance(mots, list):
        raise RuntimeError("réponse /words invalide : liste words absente")
    return mots


def charger_mots(force=False):
    with VERROU:
        valide = time.monotonic() - _cache["chargeA"] < DUREE_CACHE
        if not force and _cache["mots"] and valide:
            return list(_cache["mots"])
    config, erreur = bundles.charger_config_import()
    if erreur:
        raise RuntimeError(erreur)
    resultat, offset = [], 0
    while True:
        page = _lire_page(config, offset)
        resultat.extend(page)
        if len(page) < TAILLE_PAGE_WORKER:
            break
        offset += len(page)
        if offset > 20000:
            raise RuntimeError("pagination /words anormalement longue")
    with VERROU:
        _cache.update(chargeA=time.monotonic(), mots=resultat)
    return list(resultat)


def _filtrer(mots, connus, statuts, recherche="", niveau="", type_mot="",
             connaissance="", enrichissement=""):
    q = " ".join(str(recherche or "").split()).casefold()
    niveau = str(niveau or "").upper()
    type_mot = str(type_mot or "")
    if connaissance not in ("", "known", "not_known"):
        raise ValueError("Filtre de connaissance invalide.")
    if enrichissement not in ("", "not_started", "published", "review_required",
                              "validation_failed", "ready_to_publish"):
        raise ValueError("Filtre d'enrichissement invalide.")
    resultat = []
    for mot in mots:
        identifiant = str(mot.get("id"))
        statut = (statuts.get(identifiant) or {}).get("status")
        correspond = (
            (not niveau or mot.get("niveau") == niveau)
            and (not type_mot or mot.get("type") == type_mot)
            and (connaissance != "known" or identifiant in connus)
            and (connaissance != "not_known" or identifiant not in connus)
            and (not q or q in str(mot.get("mot", "")).casefold()
                 or q in str(mot.get("traduction", "")).casefold())
            and (not enrichissement
                 or enrichissement == "not_started" and not statut
                 or enrichissement == statut)
        )
        if correspond:
            resultat.append(mot)
    return resultat


def chercher_mots(recherche="", niveau="", offset=0, limite=50, force=False,
                  connaissance="", enrichissement="", type_mot=""):
    mots = charger_mots(force=force)
    connus = vocabulaire_progression.charger_ids_connus(force=force)
    statuts = vocabulaire_lots.statuts_par_mot()
    filtres = _filtrer(mots, connus, statuts, recherche, niveau, type_mot,
                       connaissance, enrichissement)
    offset = max(int(offset or 0), 0)
    limite = min(max(int(limite or 50), 1), 200)
    items = []
    for mot in filtres[offset:offset + limite]:
        copie, info = dict(mot), statuts.get(str(mot.get("id")), {})
        copie.update(
            knowledgeStatus="known" if str(mot.get("id")) in connus else "not_known",
            enrichmentStatus=info.get("status", "not_started"),
            batchId=info.get("batchId"), publishedAt=info.get("publishedAt"),
        )
        items.append(copie)
    types = sorted({str(mot.get("type")) for mot in mots if mot.get("type")})
    return {"items": items, "total": len(filtres), "corpusTotal": len(mots),
            "knownTotal": len(connus), "offset": offset, "limit": limite,
            "types": types}


def selectionner_prochains(limite=50, niveau="", type_mot="", connaissance=""):
    limite = int(limite or 50)
    if limite not in vocabulaire_lots.TAILLES_AUTORISEES:
        raise ValueError("Taille de lot autorisée : 10, 20, 25 ou 50.")
    mots = charger_mots()
    connus = vocabulaire_progression.charger_ids_connus()
    statuts = vocabulaire_lots.statuts_par_mot()
    filtres = _filtrer(mots, connus, statuts, niveau=niveau, type_mot=type_mot,
                       connaissance=connaissance, enrichissement="not_started")
    return [str(mot.get("id")) for mot in sorted(
        filtres, key=lambda mot: str(mot.get("id")))[:limite]]


def detailler_mots(identifiants):
    """Retourne les mots demandés dans l'ordre de la sélection automatique."""
    ids = [str(identifiant) for identifiant in identifiants]
    mots = {str(mot.get("id")): mot for mot in charger_mots()}
    connus = vocabulaire_progression.charger_ids_connus()
    statuts = vocabulaire_lots.statuts_par_mot()
    resultat = []
    for identifiant in ids:
        if identifiant not in mots:
            continue
        copie, info = dict(mots[identifiant]), statuts.get(identifiant, {})
        copie.update(
            knowledgeStatus="known" if identifiant in connus else "not_known",
            enrichmentStatus=info.get("status", "not_started"),
            batchId=info.get("batchId"), publishedAt=info.get("publishedAt"),
        )
        resultat.append(copie)
    return resultat


def creer_lot(identifiants):
    mots = {str(mot.get("id")): mot for mot in charger_mots()}
    return vocabulaire_lots.creer(identifiants, mots)


def supprimer_mots(identifiants):
    mots = {str(mot.get("id")): mot for mot in charger_mots()}
    _ids, resultat = vocabulaire_suppression.supprimer(identifiants, mots)
    vider_cache()
    return resultat


def etat_ollama():
    return ollama_vocabulaire.etat()


def generer_avec_ollama(identifiants, modele):
    if not 1 <= len(identifiants) <= 10:
        raise ValueError("Le mode local est limité à 10 mots par lot sur ce Mac.")
    lot = creer_lot(identifiants)
    resultat = ollama_vocabulaire.generer(lot["prompt"], modele)
    detail = vocabulaire_lots.importer(lot["batchId"], resultat["text"])
    return {"batch": detail["batch"], "model": resultat["model"]}
