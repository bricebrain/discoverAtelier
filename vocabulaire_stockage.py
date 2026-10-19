# -*- coding: utf-8 -*-
"""Persistance atomique des lots locaux d'enrichissement."""

import datetime
import json
import os
import tempfile
import threading


DOSSIER = os.environ.get("ATELIER_DOSSIER_REVISIONS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "vocabularyRevisions")
CHEMIN = os.path.join(DOSSIER, "revisions.json")
VERROU = threading.RLock()


def maintenant():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lire():
    with VERROU:
        try:
            with open(CHEMIN, encoding="utf-8") as fichier:
                etat = json.load(fichier)
        except (FileNotFoundError, OSError, ValueError):
            etat = {}
    if not isinstance(etat, dict):
        etat = {}
    lots = etat.get("batches")
    if not isinstance(lots, dict):
        lots = {}
    return {
        "schemaVersion": 2,
        "activeBatchId": etat.get("activeBatchId"),
        "batches": lots,
        "legacyProposals": etat.get("legacyProposals", etat.get("proposals", {})),
    }


def ecrire(etat):
    os.makedirs(DOSSIER, exist_ok=True)
    etat["schemaVersion"] = 2
    etat["updatedAt"] = maintenant()
    with VERROU:
        descripteur, temporaire = tempfile.mkstemp(dir=DOSSIER, prefix=".tmp-")
        try:
            with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
                json.dump(etat, fichier, ensure_ascii=False, indent=2)
            os.replace(temporaire, CHEMIN)
        except BaseException:
            if os.path.exists(temporaire):
                os.remove(temporaire)
            raise


def lot_actif(etat=None):
    etat = etat or lire()
    return etat["batches"].get(etat.get("activeBatchId"))
