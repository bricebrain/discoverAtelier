# D2 — Articles Explorer dans les dossiers

19 octobre 2026. Branche `codex/d2`, base `85a17fa` (`feat/lot1`).
Worktree `/private/tmp/convert-codex-d2` ; le checkout principal et sa branche ne sont pas modifiés.

Contrat complet pour Opus : `discover-mymind/docs/CODEX_D2.md` sur la branche Discover `codex/d2`
(worktree `/private/tmp/discover-mymind-codex-d2`). Aucun changement de migration D1.

- `discover_dossier.py` accepte les instantanés `type: article`, `kind: article`, `contentStatus: complete`.
  Le texte est celui capturé par le Worker, jamais récupéré par le pipeline du dossier.
- Cache `article-<id Explorer>` ; découpage en passages du texte et conservation des paragraphes issus du récupérateur
  `discover_articles.py`. `discover_source.py` conserve la langue de l’article quand elle est fournie.
- Attribution `Titre (article, Journal)` dans les données envoyées aux modèles et `Journal · Titre` dans les sources publiées,
  comme les notes Article. Provenance sans horodatage inventé, quiz et coûts utilisent la chaîne existante.
- Les textes incomplets sont bloqués avant bail par le Worker et récupérés par la file `/atelier/article-texts`, déjà
  traitée pendant l’inactivité du préparateur normal. La défense Atelier refuse aussi un instantané incomplet.
- Les contrats partagés ajoutent `article` dans `content.sources[].type` ; intégrer la branche Discover avec celle-ci.
  Aucun changement aux fichiers vocabulaire, aucun cookie ni contournement, aucun appel payant réel.

Test ajouté dans `tests/test_discover_dossier_e2e.py` : dossier avec épisode et article Explorer (ainsi que les sources
existantes), vraie synthèse/validation/publication orchestrées, transports IA/TTS/médias/Worker simulés et connexions
externes interdites. Contrôles des deux paragraphes d’article, attribution, provenance, quiz et coûts. Un second test
refuse un article partiel avant tout appel IA.

Commande de validation :

```sh
DISCOVER_CONTRACTS_DIR=/private/tmp/discover-mymind-codex-d2/contracts python3 -m unittest discover -s tests -q
```

Les serveurs HTTP de test ont besoin d’écouter sur `127.0.0.1`.
Aucun déploiement, aucun appel payant réel, aucune modification du checkout principal.

Résultat final : **254 tests réussis**, y compris la nouvelle fixture de contrat article. `git diff --check` réussi.
Un ResourceWarning existant de nettoyage d’un faux HTTPError subsiste sans échec de test.
