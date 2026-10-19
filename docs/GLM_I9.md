# GLM — Chantier I9 : coûts visibles dans l'Atelier

Branche : `glm/i9-couts` (dépôt `convert/`), créée depuis le HEAD de `feat/lot1` (`fdccf56`) — `main` est très en
retard (« version initiale ») et tout le code Discover de l'Atelier est commité sur `feat/lot1`. Le travail vocabulaire
non commité de l'utilisateur est resté en place, inchangé et non versionné dans mes commits. Aucun fichier du
périmètre interdit (`interface.html`, `convertisseur_web.py`, `bundles.py`, `README.md`, `.gitignore`, `vocabulaire*`)
n'a été modifié. Aucun changement côté `discover-mymind/` (PWA/Worker) : pas de worktree nécessaire.

## Fichiers

| Fichier | Changement |
|---|---|
| `discover_costs.py` | **Nouveau.** Tarifs par modèle, `Registre` SQLite (`costs.sqlite` à la racine de la file, à côté du registre `.deepgram/usage.sqlite`), `enregistrer()` idempotent, `rapport()` pour l'interface. |
| `discover_preparation.py` | Petit point d'intégration : un appel `discover_costs.enregistrer(...)` après une publication réussie, sous `try/except` (le suivi des coûts ne peut pas faire échouer une publication ; un échec s'affiche en une ligne dans le Terminal). |
| `discover_http.py` | Route locale `GET /api/discover/costs` (accès localhost uniquement, comme les autres routes Discover). |
| `discover_queue.html` | Bloc « Coûts · IA et voix » dans l'onglet Contrôles (jetons CSS existants, `details` repliable, ouvert par défaut). |
| `discover_queue.js` | `renderCosts` / `loadCosts` (textContent uniquement, aucun HTML injecté), rafraîchis à l'ouverture de l'onglet puis toutes les 30 s. |
| `config_discover.example.json` | Clé `pricing` d'exemple (USD par million de jetons, entrée et sortie, par modèle). |
| `tests/test_discover_costs.py` | **Nouveau.** 14 tests (voir ci-dessous). |

## Choix

- **Tarifs configurables, valeurs par défaut prudentes — À VÉRIFIER** (je ne les présente pas comme exactes) :
  `gemini-3.1-flash-lite` 0,20 / 0,80 USD par million de jetons (double du flash-lite historique, par prudence),
  `gpt-5-mini` 0,25 / 2,00, et une entrée `*` (1,00 / 4,00) qui majore tout modèle inconnu pour ne jamais
  sous-estimer. Ils se surchargent sans toucher au code via `pricing` dans `config_discover.json` ; une entrée
  invalide est ignorée (jamais de crash de préparation). L'interface affiche « tarifs par défaut à vérifier » tant
  que `pricing` n'est pas personnalisé.
- **Idempotence** : clé de ligne = empreinte SHA-256 de [id de demande, options, révision]. Une reprise (même
  demande, mêmes options, même révision) remplace la ligne au lieu d'en ajouter une ; une régénération (bump de
  `revision.json`) crée une nouvelle ligne, car c'est une nouvelle dépense réelle.
- **Mois** : les totaux Deepgram du mois viennent du registre du budget existant (`.deepgram/usage.sqlite`, lu en
  lecture seule) — c'est la source exacte de ce qui a été engagé. Les totaux Gemini/OpenAI viennent du nouveau
  registre. Total du mois = Deepgram + Gemini + OpenAI.
- **Coût Deepgram par préparation** : l'estimation engagée (`audio-estimate.json` : nouveaux caractères ×
  0,03 USD / 1 000) quand la voix finale est Deepgram ; 0 si Heart/Kokoro, avec la raison du repli conservée.
- **Aucune clé API** n'est lue au-delà de la clé `pricing`, ni affichée ni journalisée (test dédié :
  `test_aucune_cle_api_ne_sort_jamais`).

## Tests (acceptation du brief)

- `tests/test_discover_costs.py` : préparation simulée de bout en bout (client factice, transports/moteurs factices)
  → le coût apparaît **une seule fois** dans le mois après une reprise ; Deepgram (registre du budget) et IA sont
  **additionnés** ; tarifs modifiables **sans changer le code** ; modèle inconnu → tarif prudent `*` ; mois précédent
  rapporté ; voix, repli et jetons consignés ; un échec d'enregistrement n'interrompt pas une publication réussie ;
  la route renvoie les deux mois et les 20 dernières préparations ; aucune clé ne sort.

## Commandes et résultats

- `python3 -m unittest discover -s tests -q` → **213 tests OK** (199 avant le chantier, 14 nouveaux).
- `node --check discover_queue.js` → OK ; `config_discover.example.json` validé en JSON.

## Limites

- Les coûts IA comptent les appels *utilisés* par la préparation, y compris les réponses venues du cache local
  `gemini-cache` et les tentatives invalidées puis corrigées : un cache partagé entre deux préparations est compté
  dans chacune (légère surestimation possible par préparation ; le mois somme donc ces réutilisations).
- L'enregistrement a lieu en fin de préparation **publiée** : une préparation en échec définitif ou bloquée en
  relecture avant l'audio n'a pas de ligne (son IA n'est donc pas comptée — sous-estimation possible ; le mois
  Deepgram reste exact via le registre du budget).
- En cas de repli Heart *en cours* de génération, la ligne de la préparation affiche 0 USD Deepgram alors que le
  total mensuel (registre du budget) compte bien les fragments déjà engagés.
- Mois UTC, budget de cet Atelier uniquement (cohérent avec le panneau « Voix et budget audio »).
- Les montants sont des estimations à partir des tarifs configurés, pas une facturation.

## Étapes manuelles (pour Opus / l'utilisateur)

1. Vérifier les tarifs réels des modèles utilisés puis, si besoin, ajouter la clé `pricing` dans
   `config_discover.json` (le bloc « Coûts » signale tant que ce sont les valeurs par défaut).
2. Relancer l'Atelier, ouvrir la page `/discover` → onglet **Contrôles** : le bloc « Coûts · IA et voix » se remplit
   dès la prochaine préparation aboutie (les préparations antérieures à ce chantier n'y figurent pas).
3. Relecture puis fusion de la branche par Opus ; rien à déployer côté Worker.
