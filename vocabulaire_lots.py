# -*- coding: utf-8 -*-
"""Cycle de vie local des lots d'enrichissement vocabulaire."""

import hashlib
import json
import uuid

import vocabulaire_prompt
import vocabulaire_publication
import vocabulaire_stockage
from vocabulaire_validation import valider_reponse


TAILLES_AUTORISEES = {10, 20, 25, 50}
STATUTS_ENTREE = {
    "response_imported", "review_required", "ready_to_publish",
    "rejected", "published", "publish_failed",
}


def _batch_id():
    jour = vocabulaire_stockage.maintenant().replace("-", "").replace(":", "")[:15]
    return f"batch-{jour}-{uuid.uuid4().hex[:8]}"


def creer(identifiants, mots_par_id):
    ids = list(dict.fromkeys(str(item).strip() for item in identifiants if str(item).strip()))
    if not 1 <= len(ids) <= 50:
        raise ValueError("Sélectionnez entre 1 et 50 mots.")
    inconnus = [identifiant for identifiant in ids if identifiant not in mots_par_id]
    if inconnus:
        raise ValueError("Mots introuvables : " + ", ".join(inconnus[:10]))
    batch_id = _batch_id()
    sources = [vocabulaire_prompt.source_depuis_mot(mots_par_id[identifiant])
               for identifiant in ids]
    prompt = vocabulaire_prompt.construire(batch_id, sources)
    maintenant = vocabulaire_stockage.maintenant()
    lot = {
        "batchId": batch_id, "schemaVersion": 1, "status": "prompt_generated",
        "ids": ids, "sourceEntries": sources, "entries": {}, "errors": [],
        "missing": [], "extra": [], "prompt": prompt,
        "promptHash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "createdAt": maintenant, "updatedAt": maintenant,
    }
    etat = vocabulaire_stockage.lire()
    etat["batches"][batch_id] = lot
    etat["activeBatchId"] = batch_id
    vocabulaire_stockage.ecrire(etat)
    return lot


def importer(batch_id, texte):
    etat = vocabulaire_stockage.lire()
    lot = etat["batches"].get(str(batch_id))
    if not lot:
        raise ValueError("Lot introuvable.")
    rapport = valider_reponse(texte, lot)
    maintenant = vocabulaire_stockage.maintenant()
    for item in rapport["entries"]:
        proposition = item["proposed"]
        statut = "review_required" if proposition["reviewRequired"] else "response_imported"
        lot["entries"][item["id"]] = {
            "status": statut, "proposed": proposition,
            "warnings": item["warnings"], "updatedAt": maintenant,
        }
    lot.update(
        errors=rapport["errors"], missing=rapport["missing"], extra=rapport["extra"],
        responseRaw=str(texte), updatedAt=maintenant,
        status="validation_failed" if rapport["errors"] else "response_imported",
    )
    vocabulaire_stockage.ecrire(etat)
    return detail(batch_id, etat)


def changer_statut(batch_id, identifiant, statut):
    if statut not in STATUTS_ENTREE:
        raise ValueError("Statut d'entrée invalide.")
    etat = vocabulaire_stockage.lire()
    lot = etat["batches"].get(str(batch_id))
    item = (lot or {}).get("entries", {}).get(str(identifiant))
    if not item:
        raise ValueError("Entrée de lot introuvable.")
    item["status"] = statut
    item["updatedAt"] = vocabulaire_stockage.maintenant()
    lot["updatedAt"] = item["updatedAt"]
    _recalculer_statut(lot)
    vocabulaire_stockage.ecrire(etat)
    return item


def approuver_tout(batch_id):
    """Approuve toutes les propositions valides encore en attente."""
    etat = vocabulaire_stockage.lire()
    lot = etat["batches"].get(str(batch_id))
    if not lot:
        raise ValueError("Lot introuvable.")
    maintenant = vocabulaire_stockage.maintenant()
    modifies = 0
    for item in lot.get("entries", {}).values():
        if item.get("status") in {"response_imported", "review_required"}:
            item["status"] = "ready_to_publish"
            item["updatedAt"] = maintenant
            modifies += 1
    if not modifies:
        raise ValueError("Aucune proposition en attente à approuver.")
    lot["updatedAt"] = maintenant
    _recalculer_statut(lot)
    vocabulaire_stockage.ecrire(etat)
    return {"approved": modifies, **detail(batch_id, etat)}


def modifier(batch_id, identifiant, proposition):
    etat = vocabulaire_stockage.lire()
    lot = etat["batches"].get(str(batch_id))
    if not lot or str(identifiant) not in lot["ids"]:
        raise ValueError("Entrée de lot introuvable.")
    source = next(item for item in lot["sourceEntries"] if item["id"] == str(identifiant))
    mini_lot = {"batchId": lot["batchId"], "ids": [str(identifiant)],
                "sourceEntries": [source]}
    texte = json.dumps({"schemaVersion": 1, "batchId": lot["batchId"],
                        "entries": [proposition]}, ensure_ascii=False)
    rapport = valider_reponse(texte, mini_lot)
    if rapport["errors"] or not rapport["entries"]:
        raise ValueError(" ; ".join(rapport["errors"][:20]))
    valide = rapport["entries"][0]
    statut = "review_required" if valide["proposed"]["reviewRequired"] else "response_imported"
    lot["entries"][str(identifiant)] = {
        "status": statut, "proposed": valide["proposed"],
        "warnings": valide["warnings"], "updatedAt": vocabulaire_stockage.maintenant(),
    }
    lot["updatedAt"] = vocabulaire_stockage.maintenant()
    _recalculer_statut(lot)
    vocabulaire_stockage.ecrire(etat)
    return lot["entries"][str(identifiant)]


def publier(batch_id, partiel=False):
    etat = vocabulaire_stockage.lire()
    lot = etat["batches"].get(str(batch_id))
    if not lot:
        raise ValueError("Lot introuvable.")
    try:
        resultat = vocabulaire_publication.publier(lot, partiel=partiel)
    except (RuntimeError, ValueError):
        lot["status"] = "publish_failed"
        lot["updatedAt"] = vocabulaire_stockage.maintenant()
        vocabulaire_stockage.ecrire(etat)
        raise
    publies = set(resultat.get("ids") or [])
    for identifiant, item in lot["entries"].items():
        if identifiant in publies:
            item["status"] = "published"
            item["publishedAt"] = resultat.get("publishedAt")
    lot["status"] = "published"
    lot["publishedAt"] = resultat.get("publishedAt")
    lot["publication"] = resultat
    lot["updatedAt"] = vocabulaire_stockage.maintenant()
    vocabulaire_stockage.ecrire(etat)
    return resultat


def supprimer(batch_id):
    """Abandonne un lot local non publié et libère ses mots."""
    etat = vocabulaire_stockage.lire()
    lot = etat["batches"].get(str(batch_id))
    if not lot:
        raise ValueError("Lot introuvable.")
    deja_publie = lot.get("status") == "published" or any(
        item.get("status") == "published"
        for item in lot.get("entries", {}).values())
    if deja_publie:
        raise ValueError("Un lot déjà publié ne peut pas être supprimé.")
    del etat["batches"][str(batch_id)]
    if etat.get("activeBatchId") == str(batch_id):
        restants = sorted(
            etat["batches"].values(),
            key=lambda item: item.get("updatedAt", ""), reverse=True)
        etat["activeBatchId"] = restants[0]["batchId"] if restants else None
    vocabulaire_stockage.ecrire(etat)
    return detail("", etat)


def _recalculer_statut(lot):
    statuts = {item.get("status") for item in lot.get("entries", {}).values()}
    if statuts and statuts <= {"published", "rejected"}:
        lot["status"] = "published"
    elif "ready_to_publish" in statuts:
        lot["status"] = "ready_to_publish"
    elif lot.get("errors"):
        lot["status"] = "validation_failed"
    elif statuts:
        lot["status"] = "response_imported"


def detail(batch_id="", etat=None):
    etat = etat or vocabulaire_stockage.lire()
    identifiant = str(batch_id or etat.get("activeBatchId") or "")
    lot = etat["batches"].get(identifiant)
    if not lot:
        return {"batch": None, "batches": _resumes(etat)}
    copie = json.loads(json.dumps(lot, ensure_ascii=False))
    return {"batch": copie, "batches": _resumes(etat)}


def _resumes(etat):
    lots = sorted(etat["batches"].values(), key=lambda lot: lot.get("createdAt", ""), reverse=True)
    return [{"batchId": lot["batchId"], "status": lot.get("status"),
             "count": len(lot.get("ids", [])), "createdAt": lot.get("createdAt"),
             "publishedAt": lot.get("publishedAt")} for lot in lots]


def statuts_par_mot():
    etat = vocabulaire_stockage.lire()
    resultat = {}
    lots = sorted(etat["batches"].values(), key=lambda lot: lot.get("updatedAt", ""))
    for lot in lots:
        for identifiant in lot.get("ids", []):
            item = lot.get("entries", {}).get(identifiant)
            resultat[identifiant] = {
                "status": (item or {}).get("status", lot.get("status", "selected")),
                "batchId": lot["batchId"],
                "publishedAt": (item or {}).get("publishedAt"),
            }
    return resultat
