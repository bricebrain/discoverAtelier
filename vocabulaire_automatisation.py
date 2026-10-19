# -*- coding: utf-8 -*-
"""Migration API en arriere-plan avec generation puis audit croise."""

import json
import threading
import time

import vocabulaire
import vocabulaire_ia_clients
import vocabulaire_ia_config
import vocabulaire_lots
import vocabulaire_prompt
import vocabulaire_progression
import vocabulaire_stockage
from vocabulaire_ia_schema import SCHEMA_LOT


class MigrationVocabulaire:
    def __init__(self):
        self._verrou = threading.RLock()
        self._arret = threading.Event()
        self._thread = None
        self._etat = self._nouvel_etat()

    @staticmethod
    def _nouvel_etat():
        return {
            "status": "idle", "total": 0, "processed": 0, "published": 0,
            "failed": 0, "currentBatchId": None, "currentWords": [],
            "message": "Pret.", "error": None, "startedAt": None,
            "updatedAt": vocabulaire_stockage.maintenant(),
            "usage": {"inputTokens": 0, "outputTokens": 0, "calls": 0},
        }

    def instantane(self):
        with self._verrou:
            copie = json.loads(json.dumps(self._etat, ensure_ascii=False))
        copie["config"] = vocabulaire_ia_config.etat()
        return copie

    def demarrer(self, connaissance="not_known", limite=0):
        with self._verrou:
            if self._thread and self._thread.is_alive():
                raise ValueError("Une migration automatique est deja en cours.")
        config = vocabulaire_ia_config.charger()
        if not config.get("openaiApiKey") or not config.get("geminiApiKey"):
            raise ValueError("Configurez les deux cles API avant de demarrer.")
        if connaissance not in {"", "not_known"}:
            raise ValueError("Perimetre de migration invalide.")
        mots = vocabulaire.charger_mots()
        eligibles = vocabulaire._filtrer(  # filtrage metier deja utilise par l'ecran
            mots, vocabulaire_progression.charger_ids_connus(),
            vocabulaire_lots.statuts_par_mot(), connaissance=connaissance,
            enrichissement="not_started")
        ids_eligibles = {str(mot["id"]) for mot in eligibles}
        ids = [str(mot["id"]) for mot in sorted(mots, key=lambda item: str(item["id"]))
               if str(mot["id"]) in ids_eligibles]
        limite = max(int(limite or 0), 0)
        if limite:
            ids = ids[:limite]
        if not ids:
            raise ValueError("Aucun mot non commence dans ce perimetre.")
        self._arret.clear()
        with self._verrou:
            self._etat = self._nouvel_etat()
            self._etat.update(status="running", total=len(ids),
                              message="Migration automatique en cours...",
                              startedAt=vocabulaire_stockage.maintenant())
            self._thread = threading.Thread(
                target=self._executer, args=(ids, config), daemon=True,
                name="migration-vocabulaire-api")
            self._thread.start()
        return self.instantane()

    def arreter(self):
        with self._verrou:
            if not self._thread or not self._thread.is_alive():
                raise ValueError("Aucune migration n'est en cours.")
            self._etat["status"] = "stopping"
            self._etat["message"] = "Arret apres le lot en cours..."
            self._arret.set()
        return self.instantane()

    def _maj(self, **valeurs):
        with self._verrou:
            self._etat.update(valeurs, updatedAt=vocabulaire_stockage.maintenant())

    def _usage(self, resultat):
        with self._verrou:
            usage = self._etat["usage"]
            usage["inputTokens"] += int(resultat.get("inputTokens") or 0)
            usage["outputTokens"] += int(resultat.get("outputTokens") or 0)
            usage["calls"] += 1

    @staticmethod
    def _objet_propose(lot):
        entrees = lot.get("entries") or {}
        return {
            "schemaVersion": 1, "batchId": lot["batchId"],
            "entries": [entrees[identifiant]["proposed"] for identifiant in lot["ids"]],
        }

    def _appel_avec_reprises(self, provider, modele, cle, prompt, config):
        derniere = None
        for tentative in range(config["maxRetries"] + 1):
            if tentative:
                self._maj(message=f"Nouvelle tentative {provider} "
                          f"{tentative}/{config['maxRetries']} apres une erreur API...")
                time.sleep(min(2 ** tentative, 8))
            try:
                resultat = vocabulaire_ia_clients.generer(
                    provider, prompt, modele, cle, SCHEMA_LOT)
                self._usage(resultat)
                return resultat
            except RuntimeError as erreur:
                derniere = erreur
        raise derniere or RuntimeError("Echec de l'appel IA.")

    def _traiter_lot(self, ids, config):
        lot = vocabulaire.creer_lot(ids)
        self._maj(currentBatchId=lot["batchId"],
                  currentWords=[item["word"] for item in lot["sourceEntries"]])
        detail = None
        prompt_generation = lot["prompt"]
        for tentative in range(config["maxRetries"] + 1):
            generation = self._appel_avec_reprises(
                "gemini", config["generatorModel"], config["geminiApiKey"],
                prompt_generation, config)
            detail = vocabulaire_lots.importer(lot["batchId"], generation["text"])
            erreurs = detail["batch"].get("errors") or []
            if not erreurs:
                break
            prompt_generation = lot["prompt"] + (
                "\n\nCORRECTION OBLIGATOIRE DE LA REPONSE PRECEDENTE\n" +
                "\n".join(erreurs[:8]))
        if detail["batch"].get("errors"):
            raise RuntimeError("Generation Gemini invalide : " +
                               " ; ".join(detail["batch"]["errors"][:3]))
        candidat = self._objet_propose(detail["batch"])
        prompt_audit = vocabulaire_prompt.construire_audit(lot, candidat)
        final = None
        for tentative in range(config["maxRetries"] + 1):
            audit = self._appel_avec_reprises(
                "openai", config["auditorModel"], config["openaiApiKey"],
                prompt_audit, config)
            final = vocabulaire_lots.importer(lot["batchId"], audit["text"])
            erreurs = final["batch"].get("errors") or []
            if not erreurs:
                break
            prompt_audit += ("\n\nCorrige imperativement ces erreurs de schema :\n" +
                             "\n".join(erreurs[:8]))
        batch = final["batch"]
        if batch.get("errors") or len(batch.get("entries") or {}) != len(ids):
            detail_erreur = " ; ".join((batch.get("errors") or ["lot incomplet"])[:3])
            raise RuntimeError("Audit OpenAI invalide : " + detail_erreur)
        vocabulaire_lots.approuver_tout(lot["batchId"])
        if config["autoPublish"]:
            derniere = None
            for tentative in range(config["maxRetries"] + 1):
                if tentative:
                    time.sleep(min(2 ** tentative, 8))
                try:
                    resultat = vocabulaire_lots.publier(lot["batchId"])
                    return len(resultat.get("ids") or [])
                except RuntimeError as erreur:
                    derniere = erreur
            raise derniere or RuntimeError("Echec de la publication automatique.")
        return 0

    def _executer(self, ids, config):
        taille = config["batchSize"]
        try:
            for debut in range(0, len(ids), taille):
                if self._arret.is_set():
                    self._maj(status="stopped", message="Migration arretee.")
                    return
                bloc = ids[debut:debut + taille]
                publies = self._traiter_lot(bloc, config)
                with self._verrou:
                    self._etat["processed"] += len(bloc)
                    self._etat["published"] += publies
                    self._etat["message"] = (
                        f"{self._etat['processed']} / {self._etat['total']} mots traites")
                    self._etat["updatedAt"] = vocabulaire_stockage.maintenant()
            self._maj(status="completed", currentBatchId=None, currentWords=[],
                      message="Migration terminee sans validation manuelle.")
        except Exception as erreur:
            batch_id = self._etat.get("currentBatchId")
            if batch_id:
                try:
                    lot = vocabulaire_lots.detail(batch_id).get("batch") or {}
                    if lot.get("status") != "publish_failed":
                        vocabulaire_lots.supprimer(batch_id)
                except (RuntimeError, ValueError):
                    pass
            with self._verrou:
                self._etat["failed"] += len(self._etat.get("currentWords") or [])
            self._maj(status="failed", error=str(erreur),
                      message="Migration interrompue. Le dernier lot peut etre relance.")


MIGRATION = MigrationVocabulaire()
