window.VocabulaireApi = {
  async requete(chemin, corps) {
    const options = corps === undefined ? {} : {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify(corps),
    };
    const reponse = await fetch(chemin, options);
    const resultat = await reponse.json().catch(() => ({erreur:"Réponse illisible du serveur."}));
    if (!reponse.ok) throw new Error(resultat.erreur || `Erreur HTTP ${reponse.status}`);
    return resultat;
  },
  mots(parametres) { return this.requete(`/api/vocabulaire/mots?${parametres}`); },
  lot(batchId="") { return this.requete(`/api/vocabulaire/lot?batchId=${encodeURIComponent(batchId)}`); },
  prochains(parametres) { return this.requete(`/api/vocabulaire/prochains?${parametres}`); },
  creerLot(ids) { return this.requete("/api/vocabulaire/lot", {ids}); },
  importer(batchId, texte) { return this.requete("/api/vocabulaire/lot/importer", {batchId, texte}); },
  statut(batchId, id, statut) { return this.requete("/api/vocabulaire/lot/statut", {batchId,id,statut}); },
  approuverTout(batchId) { return this.requete("/api/vocabulaire/lot/approuver", {batchId}); },
  editer(batchId, id, proposition) { return this.requete("/api/vocabulaire/lot/editer", {batchId,id,proposition}); },
  publier(batchId, partiel) { return this.requete("/api/vocabulaire/lot/publier", {batchId,partiel}); },
  supprimerLot(batchId) { return this.requete("/api/vocabulaire/lot/supprimer", {batchId}); },
  supprimer(ids) { return this.requete("/api/vocabulaire/supprimer", {ids}); },
  iaEtat() { return this.requete("/api/vocabulaire/ia"); },
  iaConfigurer(config) { return this.requete("/api/vocabulaire/ia/config", config); },
  iaDemarrer(connaissance, limite) { return this.requete("/api/vocabulaire/ia/demarrer", {connaissance,limite}); },
  iaArreter() { return this.requete("/api/vocabulaire/ia/arreter", {}); },
};
