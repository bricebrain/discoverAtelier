# A5 — Quiz pour toutes les préparations et dossier simulé

19 octobre 2026. Dépôt Atelier `convert`, worktree `/private/tmp/convert-codex-a5`,
branche `codex/a5-quiz-dossier`, base `59b9ae7` (`feat/lot1`).
Aucune modification de la branche ou des fichiers du checkout principal `convert/`.

## Résultat et types couverts

Le branchement était déjà commun : `discover_preparation.preparer` appelle
`discover_quiz.generer` après la production du texte final, puis transmet le quiz au
constructeur de manifeste et les appels IA au registre `discover_costs`.
Aucun ajout de branchement ni changement de code de production n'est nécessaire.

Les nouvelles simulations vérifient chaque type :

- podcast ;
- vidéo YouTube ;
- réflexion personnelle My Mind ;
- article My Mind, avec attribution à son journal ;
- dossier multisources.

Pour chacun : trois questions en anglais au niveau demandé, index rattachés aux
paragraphes publiés, quiz uniquement sur l'adaptation, coût `quizUsd` inclus une
seule fois dans le total fournisseur. Le transport simulé utilise 1 000 jetons en
entrée et 500 en sortie ; le modèle de test reçoit le tarif prudent `*` du code :
0,003 USD simulé pour le quiz, sans dépense réelle. Les trois réponses invalides
consomment 0,009 USD simulé, tous les essais étant comptés. Une panne sans réponse
ou une désactivation n'enregistre aucun coût de quiz. Dans ces trois cas, le
contenu continue à être publié sans questions.

Les tests existants de Q couvrent aussi le cache, les rejets de validation, le
registre historique et le calcul OpenAI ; ils restent verts.

## Parcours dossier réellement exécuté

`FileDiscover._executer` prend un bail auprès du faux Worker, puis appelle le vrai
aiguillage `discover_source.preparer_source` et `discover_dossier.preparer`.
Cinq sources sont assemblées : podcast, vidéo YouTube suivie, réflexion, article
My Mind, contenu déjà préparé. Le format YouTube du dossier suit le vrai Worker :
`type=episode`, référence d'épisode, `kind=youtube`, `videoId` distinct.

Le découpage des textes, les empreintes, la provenance, le plan, l'extraction,
l'écriture, l'évaluation, le quiz, le paquet, les validateurs de contrat et
`publier_manifeste` s'exécutent réellement. Seuls les téléchargements/transcriptions
média, le transport IA, la voix et le transport HTTP sont simulés. Les réponses IA
passent par le vrai `Client`, ses schémas et ses validateurs.

Le faux Worker contrôle le bail et l'ordre déclaration → envois → commit, puis
vérifie taille et SHA-256 de chaque fichier. Les tests contrôlent les références
vers toutes les sources, l'attribution article/note, les consignes de désaccord,
les timings de provenance, les fichiers publiés, le registre de coûts et la fin
de demande sans publication supplémentaire.

Deux échecs sont également simulés :

- bail perdu à l'étape `publish` : aucune déclaration, aucun envoi ni commit ;
- source inaccessible : aucun appel de synthèse ni publication partielle,
  signalement d'échec à la file.

Les tests bloquent toute connexion socket et tout sous-processus externe dans
ces simulations. Aucun appel payant, déploiement ou migration n'a eu lieu.
La simulation vérifie l'orchestration et les contrats ; elle ne remplace pas une
recette éditoriale humaine ou un essai avec les services externes réels.

## Fichiers et correction

- `tests/discover_simulation.py` : faux transport IA, Worker et médias partagés.
- `tests/test_discover_preparation_types.py` : matrice des cinq types, quiz valide,
  invalide, indisponible ou désactivé, et comptabilité.
- `tests/test_discover_dossier_e2e.py` : dossier de bout en bout et interruptions.
- `tests/test_discover_queue.py` : configuration non vide explicite dans le test
  des envois sous bail. Le précédent `config={}` rechargeait le fichier local
  ignoré `config_discover.json`, absent d'un worktree propre.
- `docs/CODEX_A5.md` : ce résumé.

Aucun fichier PWA, Worker ou vocabulaire modifié. Aucun contrat changé, aucune
nouvelle dépendance. Aucune fusion dans `feat/lot1` effectuée.

## Validation

Depuis le worktree, avec les contrats du dépôt Discover :

```sh
export DISCOVER_CONTRACTS_DIR=/Users/brice/mesProjects/myMobileProjects/discover-mymind/contracts
python3 -m unittest discover -s tests -q
```

**245 tests réussis**, Python 3.15, en 10,822 s. Les tests HTTP existants nécessitent
l'autorisation d'écouter sur `127.0.0.1` ; la suite complète a été lancée avec cette
permission. Un avertissement `ResourceWarning` de nettoyage d'un faux `HTTPError`
subsiste dans la suite existante, sans échec. `git diff --check` est également vert.

Le commit porte le sujet « Tester les quiz de toutes les préparations et le dossier simulé »
et le pied de message `Co-Authored-By: Codex`.
