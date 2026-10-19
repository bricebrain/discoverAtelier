# V9-3 — Synchronisation automatique des mots dans l’Atelier

19 octobre 2026. Chantier A8 de la vague 8 repris dans l'ordre de V9.

- Discover : branche `codex/v9-3`, base `97bd74e`, worktree `/private/tmp/discover-mymind-codex-v9-3`.
- Atelier : branche `codex/v9-3`, base `b5e68b0` de `feat/lot1`, worktree `/private/tmp/convert-codex-v9-3`.
- Le checkout principal `convert/` conserve sa branche `feat/lot1` et son processus sur 53782.

## Découpage et fichiers Atelier

- **Nouveau** `discover_vocabulary_sync.py` : cadence persistante, verrou et état local. Aucun secret ni mot gardé dans cet état.
- `discover_queue.py` : appel dans la boucle inactive du préparateur normal, après les tâches articles/rapprochement ;
  absent du chemin de préparation et du mode « sources seulement ». Une erreur n'arrête pas la file.
- `discover_vocabulary_picks.py` : contrôles d'interruption avant lecture, envoi EF et accusé Discover ; progression des
  compteurs transmise à l'ordonnanceur. Le CLI utilise le même verrou que la synchronisation automatique.
- `discover_http.py` : GET local `/api/discover/vocabulary/status` ; la route POST manuelle `/api/discover/vocabulary/sync`
  utilise le même ordonnanceur et refuse le travail lorsqu'une préparation locale est active. Protections Host/Origin/CSRF
  existantes conservées. Le GET des sélections reste inchangé.
- `discover_queue.html` / `discover_queue.js` : section « Mots gardés · EnglishFluency » dans Contrôles : activation,
  état courant, dernière tentative, dernier passage terminé, dernier envoi confirmé, compteurs du dernier passage.
  Rafraîchissement à l'ouverture de Contrôles et toutes les trente secondes ; contenu injecté avec `textContent`.
- `config_discover.example.json` : `vocabularyAutoSync: true`.
- **Nouveau** `tests/test_discover_vocabulary_sync.py` : 17 tests de planification, concurrence, transferts et intégration.

Pas de bibliothèque supplémentaire, migration ni changement du contrat Worker d'envoi des mots.
Les deux nouveaux fichiers Python restent sous 300 lignes. Les modules de file et HTTP existants restent sous 300 lignes.

## Règles d’exécution

- Activé par défaut lorsque le préparateur normal tourne et reste inactif. `vocabularyAutoSync: false` coupe uniquement
  le déclenchement automatique ; les commandes manuelles restent disponibles. Relire la configuration en redémarrant le
  préparateur selon la procédure V9, après autorisation de ce lot.
- Au plus **une tentative automatique toutes les 600 secondes**, y compris après échec. L'instant est enregistré avant
  le réseau et conservé après redémarrage ; une tentative manuelle explicite peut passer avant cette échéance et repousse
  le prochain passage automatique. Arrêt du préparateur ou activité longue peuvent retarder l'envoi au-delà de dix minutes.
- Verrou `flock` local non bloquant commun à la boucle inactive, à la route manuelle et au CLI, pour un même dossier de file.
  Un deuxième processus/thread reçoit un résultat « synchronisation déjà en cours ».
- Une préparation locale active empêche le démarrage. Le serveur Discover est interrogé pour vérifier l'absence de bail
  `leased`, puis cette vérification est répétée avant chaque page, envoi EF et accusé. Un nouveau bail ou un arrêt demandé
  interrompt le passage à ce point de contrôle. Une requête HTTP déjà commencée conserve son timeout existant : l'arrêt
  ne prétend pas interrompre immédiatement une opération réseau en cours.
- Les états `pending` et `failed` sont repris avec la pagination existante ; les succès terminaux restent ignorés.
  `sourceId=discover:<id>` est conservé, sans nouvelle génération, pour bénéficier des reçus idempotents EnglishFluency.
- Arrêt après réception EF mais avant accusé Discover : compteur d'accusé manquant, sélection inchangée côté Discover et
  même identifiant lors de la reprise. Aucun mot ni accusé n'est inventé pour prétendre que le passage est complet.
- Les erreurs et reprises partielles sont journalisées avec des messages génériques, sans exception brute, payload ni secret.

## État local et API

Dans le dossier `.discover-queue/` configuré :

- `vocabulary-sync.lock` : exclusion locale, permissions 0600 ;
- `vocabulary-sync.json` : écriture atomique via l'utilitaire existant (temporaire privé, puis remplacement).

L'état expose `autoEnabled`, `intervalSeconds`, `running`, `phase` (`never`, `running`, `success`, `warning`, `error`,
`interrupted`), `lastAttemptAt`, `lastRunAt`, `lastSentAt`, `mode` et `lastReport` avec
`sent`, `already_known`, `failed`, `unacknowledged`. Les dates sont UTC ISO, rendues en heure locale dans l'Atelier.
Il ne contient ni configuration, ni jeton, ni identifiant de sélection, ni phrase. Les compteurs décrivent le dernier passage,
pas le nombre total de mots du référentiel. Le dernier envoi confirmé correspond à un succès EF accusé par Discover.
Un état resté « running » après un arrêt brutal est montré « interrompu » si le verrou n'est plus occupé.
La lecture du statut n'interroge pas EF, ne déclenche pas de synchronisation et ne lit pas de clé pour la transmettre au navigateur.

## Vérifications

| Projet | Résultat |
| --- | --- |
| Atelier | `DISCOVER_CONTRACTS_DIR=/private/tmp/discover-mymind-codex-v9-3/contracts python3 -m unittest discover -s tests -q` : **284 tests verts** |
| Discover PWA | `npm test` : **190 tests / 36 fichiers** ; `npx tsc --noEmit -p .`, `npm run build` verts |
| Discover Worker | `npm test` : **345 tests / 31 fichiers** ; `npx tsc --noEmit -p .` vert |
| EnglishFluency Worker | `npm test` : **223 tests / 17 fichiers**, verts |
| EnglishPWA | `npx tsc -b && npm test -- --run && npm run lint && npm run build` : **90 tests / 15 fichiers**, tout vert |

Contrôles complémentaires : `python3 -m py_compile` des modules changés, `node --check discover_queue.js`, `git diff --check`.
Tests dédiés : échéance inclusive et redémarrage, commandes manuelles, désactivation, préparations locales/distantes,
contrôle entre opérations, stop avant accusé, rapport partiel, erreurs sans secrets, absence de doublon concurrent,
statut interrompu après crash, code de sortie CLI en échec, non-interruption de la boucle et protections des routes HTTP. Les sept tests I1 restent verts.
La configuration de test du worktree est factice (localhost:9), ignorée et non livrée ; aucune configuration réelle copiée.

Recette visuelle du vrai HTML/JavaScript Atelier sur **53783**, avec serveur temporaire et réponses entièrement fictives :
section Contrôles, dates, compteurs, état « reprise nécessaire ». Aucun lancement de file, envoi de mots, appel IA payant,
lecture de configuration réelle ou requête de production pour cette recette. Capture : `/private/tmp/discover-v9-3-atelier.png`.
Le serveur de recette est arrêté après vérification. Le processus existant sur 53782 n'est ni arrêté ni redémarré.

Les avertissements non bloquants préexistants des suites restent présents (bundle PWA, audio de test Worker, HTTPError
Python, SQLite expérimental). Les scénarios de pannes simulent aussi les nouveaux messages génériques de reprise différée.

## Livraison et suite

Branches de travail prêtes pour revue, sans fusion ni push. Aucun déploiement ni migration en production.
L'automatisme ne tourne donc **pas encore dans l'Atelier actif**. Une intégration et un redémarrage nécessitent l'accord
explicite pour ce lot et la procédure du § 6 du brief V9 (contrôle de file inactive avant arrêt/redémarrage).
Prochain chantier : V9-4, écoute active dans la PWA.
