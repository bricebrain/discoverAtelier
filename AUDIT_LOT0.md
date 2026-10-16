# Audit LOT 0 — English Fluency (atelier, Worker, PWA)

**Date :** 16 octobre 2026
**Référence :** `CAHIER_DES_CHARGES_ENGLISH_FLUENCY_FINAL.md` (v2.0), § 11 « LOT 0 » et § 14 « Questions d'audit ».
**Décisions appliquées :**
- **profil unique** (`default`, plus `__global__` pour les contenus partagés) ;
- **les détails d'écoute active suivent la v1.2** (`CAHIER_DES_CHARGES_ECOUTE_ACTIVE.md`), qui corrige la v1.1 citée par la v2.0 ;
- **questions à 4 choix** partout, y compris le test `sound_form`, que la v2.0 décrit à 3 formes.

**L'app React Native (`englishfluency-app/`) n'est plus utilisée** (confirmé le 16/10/2026) : seule la PWA consomme le Worker.

**Seul le correctif du § 3.1 a été déployé** (avec ton accord). Rien n'a été poussé sur GitHub. Les tests sont commités en local sur des branches dédiées (§ 7).

---

## 1. Synthèse

| Domaine | État | Gravité |
|---|---|---|
| Proxy IA `/proxy/*` et routes `/tts/*` | Étaient **accessibles sans authentification**, avec tes vraies clés OpenAI, Gemini, DeepSeek, OpenRouter, Groq et xAI | ✅ Corrigé et déployé (§ 3.1) |
| Secret du Worker | Intégré en clair dans les anciennes versions compilées de l'app React Native (abandonnée) ; c'est aussi un mot simple | 🟠 Élevée : **changer le secret** |
| Lectures sans authentification | `GET /content`, `/srs/*`, `/lingvist/session`, `/learning/*`… lisibles avec un simple `profileId` | 🟠 Moyenne (données personnelles) |
| Code déployé ≠ historique git | Le Worker en production contient `srs.ts` et `learning.ts` non commités | 🟠 Moyenne |
| Liste des contenus | `GET /content` renvoie la `metadata` complète (segments, chunks) de 50 contenus | 🟡 Performance, à traiter au LOT 1 |
| Audio | Pas de requêtes Range ; cache `immutable` sur des clés fixes | 🟡 Déjà prévu au LOT 1 |
| Tests | Worker : **aucun** test avant cet audit ; PWA : tests unitaires de helpers seulement | ✅ Corrigé : 43 + 22 + 34 tests |
| Atelier `convert/` | Pas sous git : aucun historique ni retour arrière possible | 🟡 À corriger avant le LOT 1 |

**Recommandation principale :** la faille du proxy IA est corrigée (§ 3.1). Il reste à **changer le secret** (§ 3.2) et à **protéger les lectures** (§ 3.3), ce qui ne présente plus de risque puisque seule la PWA consomme le Worker.

---

## 2. Mon avis sur le cahier v2.0

Le cahier final est cohérent et réaliste. Il garde l'essentiel des versions précédentes (écoute libre prioritaire, mesure sur extraits inédits, `verified:false`, références audio versionnées) et ajoute trois choses justes :
- d'autres sources que YouTube (textes, articles, productions personnelles) ;
- la distinction **lecture / écoute** ;
- des adaptations **facultatives et fidèles** plutôt que tous les niveaux générés.

Points à garder en tête :
1. **Il s'appuie sur la v1.1, pas sur la v1.2.** Deux détails régressent : `sound_form` à 3 formes au lieu de 4, et « deux ou trois questions » par extrait de contrôle au lieu de 3 à 4 choix. Décision appliquée : **la v1.2 fait foi pour ces détails** ; la v2.0 fait foi pour tout le reste (sources, adaptations, IA, Lingvist).
2. **L'IA cloud change de statut** : de « jamais d'API » (v1.x) à « optionnelle et contrôlée ». C'est réaliste, car **les clés existent déjà** dans le Secrets Store du Worker et sont déjà utilisées (articles, Assimil, TTS). Mais c'est justement là que se trouve la faille du § 3.1 : il faut la corriger avant d'ajouter des usages.
3. **L'authentification par profil** (§ 8.3 de la v2.0, « profileId = identité authentifiée ») ne correspond pas à l'existant : un seul secret partagé, aucun compte utilisateur, une seule ligne dans `profiles`. Décision appliquée : **profil unique** ; on protège l'accès au Worker, sans gérer de comptes.
4. **Le périmètre a beaucoup grandi** (6 lots au lieu de 3). Le découpage est bon, mais l'écoute active n'arrive qu'au LOT 3, alors que le protocole de 28 jours dépend d'elle. À garder en tête si tu veux tester la méthode plus tôt.
5. Coquille : « timelimes » pour « timelines » (§ 15).

---

## 3. Sécurité

### 3.1 🔴 Proxy IA et TTS sans authentification

> **Statut (16/10/2026) : corrigé et DÉPLOYÉ** (version Worker `ff310f71`).
> - Avant le déploiement, `GET /proxy/deepseek/v1/models` sans clé répondait **200** en production.
> - Après : 401 sur les 6 cibles du proxy, les 3 routes TTS et un mauvais secret ; 200 avec le secret ; routes existantes inchangées.
> - Worker, branche `fix/auth-proxy-tts`, commit `f64d78b` : authentification obligatoire sur `/proxy/*` et `/tts/*`. 53 tests, dont 10 qui échouent sans le correctif.
> - L'adaptation de l'app React Native a été annulée : l'app n'est plus utilisée (branche supprimée, dépôt remis dans son état initial).

**Constat (vérifié dans le code et par test).**
- `src/proxy.ts` relaie `/proxy/<openai|openrouter|gemini|groq|deepseek|xai>/…` vers l'API correspondante en **ajoutant la vraie clé**, sans appeler `isAuthorized`.
- `src/tts.ts` fait de même pour `POST /tts/openai`, `/tts/gemini` et `/tts/groq`.
- Les en-têtes `Access-Control-Allow-Origin: *` permettent l'appel depuis n'importe quelle page web.

**Conséquence.** Toute personne qui connaît l'adresse `englishfluency-worker.bricebrain.workers.dev` peut consommer tes crédits OpenAI, Gemini, DeepSeek, OpenRouter, Groq et xAI.

**Preuve.** `test/securite.test.ts` :
- « constat actuel : le proxy transmet la requête à DeepSeek sans authentification » ;
- « constat actuel : /tts/openai appelle OpenAI sans authentification ».

**Correction proposée (une ligne par route, puis un déploiement).**
- Ajouter `if (!isAuthorized(req, env.API_SECRET)) return err('Non autorisé', 401);` en tête de `handleProxy`, `handleTtsOpenAi`, `handleTtsGemini` et `handleTtsGroq`.
- **Impact PWA : aucun.** Son proxy serveur (`api/backend.ts` sur Vercel, `vite.config.ts` en développement) ajoute déjà le secret à **toutes** les requêtes.
- **Impact app React Native :** aucun à prévoir, l'app n'est plus utilisée.
- Ensuite, transformer les deux tests `it.fails` correspondants en tests normaux.

### 3.2 🟠 Changer le secret du Worker

> **Statut (16/10/2026) : fait.**
> - Nouveau secret aléatoire de 64 caractères, appliqué au Worker (`API_SECRET`), à Vercel (`WORKER_SECRET`, PWA redéployée et vérifiée), à `convert/config_import.json` et à `englishPwa/.env.local`.
> - L'ancien secret est refusé (401).
> - Les lectures GET sont protégées depuis la version Worker `e20cad73` (§ 3.3).

- Les anciennes versions de l'app React Native lisaient le secret dans `EXPO_PUBLIC_WORKER_SECRET`, une variable **intégrée en clair** dans l'app compilée. L'app n'est plus utilisée, mais ses builds existants contiennent toujours le secret.
- Le secret actuel est un mot simple.
- **À faire :** générer une valeur aléatoire longue et la mettre à jour à trois endroits :
  - secret `API_SECRET` du Worker (`wrangler secret put API_SECRET`) ;
  - variable `WORKER_SECRET` de la PWA sur Vercel (et le `.env` local) ;
  - `convert/config_import.json`.
- Comme seule la PWA est concernée, le changement est simple. Les trois mises à jour doivent cependant être faites ensemble pour éviter une coupure.

### 3.3 🟠 Lectures sans authentification

Les routes GET suivantes ne vérifient pas le secret : `/content`, `/srs/stats`, `/srs/session`, `/srs/triage`, `/lingvist/session`, `/learning/mission`, `/learning/insights`, entre autres. Elles exposent ta progression et tes contenus à qui devine l'adresse et le `profileId` (`default`).

Deux tests `it.fails` le documentent. La PWA envoie déjà le secret sur toutes ses requêtes, et l'app React Native n'est plus utilisée : **les protéger est sans risque**.

`GET /audio/<clé>` doit rester public : le lecteur `<audio>` du navigateur ne peut pas envoyer d'en-tête d'authentification.

### 3.4 Autres points

- `convert/config_import.json` contient le secret en clair, en local. C'est acceptable, puisque le dossier n'est ni versionné ni partagé. Prévoir `config_import.example.json` sans secret.
- Le secret actuel est un mot simple : à remplacer par une valeur aléatoire longue au moment de la correction du § 3.1.

---

## 4. Inventaire

### 4.1 Worker (`englishfluency-worker/`)

- **95 routes** dans `src/index.ts` :
  - assimil 15, podcast-feeds 12, srs 8, words 7 ;
  - content 5, lingvist 5, srt 5 ;
  - articles, admin 4 chacun ;
  - tts, learning, reading-library, calibration, podcasts, profile 3 chacun ;
  - reste 1 à 2.
- **Authentification :** un seul secret, `Authorization: Bearer <API_SECRET>`, vérifié route par route (`isAuthorized`). Il n'existe pas de middleware commun : c'est la cause des oublis du § 3.
- **D1 : 19 tables** sur 14 migrations. `content`, `words`, `word_progress`, `review_history_daily`, `lingvist_cards`, `lingvist_calibration`, `learning_events`, `profiles`, `dictation_sessions`, `assimil_lessons`, `podcast_feeds`, `podcast_episodes`, `youtube_channels`, `srt_sources`, `srt_episodes`, `srt_scenes`, `reading_library_sources`, `reading_library_items`, `reading_library_segments`.
- **R2 :** bucket `englishfluency-audio`. Préfixes observés : `prepared-content/` (atelier), `tts/<fournisseur>/` (cache TTS).
- **Secrets Store :** OpenAI, OpenRouter, Gemini, Groq ×2, DeepSeek, xAI.
- **Modèles référencés dans le code :** `gemini-3.5-flash` (10), `deepseek-v4-flash` (9), `gpt-4o-mini`, `gpt-4o-mini-tts`, `gpt-4o-transcribe`, `whisper-1`, `gemini-2.5-flash-preview-tts`, `gemini-3.1-flash-tts-preview`. Les crédits et quotas réels ne peuvent pas être vérifiés sans appel payant (question 6 du § 6).
- **Tâche planifiée :** `17 3 * * *` (préparation Assimil).
- **Tests :** aucun avant l'audit.

### 4.2 Volumes en production (lecture seule, 16/10/2026 à 21 h)

| Table | Lignes |
|---|---|
| `words` | 4 622 |
| `word_progress` | 1 770 |
| `learning_events` | 1 954 |
| `lingvist_cards` | 336 |
| `reading_library_items` | 232 |
| `assimil_lessons` | 47 |
| `content` | 18 (4 podcasts `default`, 10 `channel_lesson` et 4 `daily_podcast` en `__global__`) |
| `profiles` | 1 |

Contenus de l'atelier en production :

| Contenu | Format | `metadata` |
|---|---|---|
| `why-tech-stocks-crash…` | ancien | 23,6 Ko |
| `pourquoi-la-can-va-repasser…` | ancien, **audio français publié** | 17,4 Ko |
| `ai-designed-viruses…` | v2 | 69,5 Ko |
| `comment-blackrock-est-devenu…` | v2, audio `-en` Kokoro | 78,1 Ko |

### 4.3 PWA (`englishPwa/`)

- **15 pages** (Accueil, Lingvist, Tri, Flashcards, Scripts, Écouter, Lire, Assimil, Phrases, Live, Statistiques, Profil, Réglages, Plus, 404).
- **19 routes du Worker appelées :**
  - `/content`, `/content/:id` ;
  - `/srs/session|review|known|triage|stats`, `/lingvist/session` ;
  - `/assimil/lessons|progress|lesson/:n` ;
  - `/articles/promote-words` ;
  - `/reading-library/items[…]/segments` ;
  - `/srt/sources[…]`, `/srt/episodes/:id/scenes` ;
  - `/tts/:fournisseur`, `/proxy/deepseek/v1/chat/completions`, `/audio/<clé>`.
- **Accès au Worker :** proxy même origine `/api` (Vercel `api/backend.ts`, Vite en développement), qui ajoute le secret côté serveur. Aucun secret dans le JavaScript livré.
- **Lecteur :** `useAudioPlayer` (positionnement, vitesse, `timeupdate`). La page Live reste locale (`localStorage`).
- **Tests :** vitest en environnement Node, sans jsdom ; aucun test de composant.

### 4.4 Atelier (`convert/`)

- Python, sans framework, interface HTML servie en local. Modules :
  - `pipeline.py` (métier) ;
  - `bundles.py` (fichiers et Worker) ;
  - `convertisseur_web.py` (serveur, jobs, Kokoro) ;
  - `transcription.py` (MacWhisper) ;
  - `tts_kokoro.py`.
- **Bundles à plat** dans `fileToImport/` : `<slug>.mp3`, `.audio-en.mp3`, `.transcript.<l>.txt`, `.translation.<l>.txt`, `.segments.json`, `.pedagogy.json`, `.meta.json`, et `_jobs.json`.
- **Publication :** upload de l'audio (`POST /content/audio`) **puis** `POST /content`. L'ordre garantit que la `metadata` ne pointe jamais vers un audio absent (question 5 du § 6).
- **Contrat publié :** `metadata` en `schemaVersion: 2`, avec les champs historiques conservés (`sourceType`, `sourceUrl`, `audioLanguage`, `transcriptLanguage`, `transcriptText`). La PWA lit encore ces champs pour les anciens contenus.
- **Pas sous git.**

### 4.5 App React Native (`englishfluency-app/`)

**N'est plus utilisée.** Seule la PWA consomme le Worker : les changements de contrat (authentification, format de `/content`) n'ont à tenir compte que d'elle. Le code de l'app reste dans son dépôt, sans modification.

---

## 5. Autres constats techniques

1. **`GET /content` est trop lourd pour une liste.**
   - La `metadata` d'un contenu v2 de 10 minutes pèse environ 75 Ko (segments, chunks, textes) ; une vidéo d'une heure dépasserait 400 Ko.
   - La page Scripts charge jusqu'à 50 contenus, soit **plusieurs Mo par affichage**.
   - D1 limite une ligne à 2 Mo environ.
   - **Proposition LOT 1 :** la liste ne renvoie qu'une `metadata` résumée ; le détail (segments, chunks, variantes) est servi par une route dédiée ou un JSON versionné dans R2.
2. **Éviction à 50 contenus.** La création d'un 51e contenu supprime la ligne la plus ancienne mais **pas son audio R2**, qui devient orphelin. À intégrer au cycle de vie des références audio (v1.2, § 8.2).
3. **PWA `submitLingvistAnswer`.** Si `card.srsWord` est absent, l'objet `word` envoyé à `/srs/review` ne contient pas les champs de progression obligatoires, et l'insertion échoue (contrainte `NOT NULL`). **À vérifier** dans l'usage réel : je ne l'ai pas reproduit dans l'app.
4. **Historique git du Worker.** La production (version `6a6b4eb8`) contient les modifications non commitées de `srs.ts` et `learning.ts`. Les tests de cet audit portent sur ce code-là.
5. **CAN publiée avec l'audio français** (ancien import) : à republier depuis l'atelier.

---

## 6. Réponses aux questions d'audit (§ 14 du cahier v2.0)

1. **Profils et authentification.**
   - Un seul secret partagé et aucun compte : `profileId` est un paramètre libre envoyé par le client.
   - `word_progress` et `lingvist_cards` utilisent la clé `{profileId}_{wordId}` ; `content` a un `profile_id`, avec la convention `__global__` pour les contenus partagés.
   - **Décision : profil unique `default`.** On sécurise l'accès au Worker (§ 3), pas les profils. Une vraie authentification par utilisateur n'a de sens que si l'app devient multi-utilisateur.
2. **`metadata` ou table `content_variants` ?**
   - À court terme, `metadata` suffit pour **une** variante par contenu ; elle est déjà en place et testée.
   - Dès qu'il y a plusieurs variantes (LOT 4) ou des segments volumineux, il faut une **table `content_variants`**, avec les segments en JSON versionné dans R2 ou dans D1 selon la taille.
   - **Source de vérité proposée :** D1 pour l'identité, les révisions et les références ; R2 pour les gros documents immuables (segments, audio) ; `metadata` réduite à un résumé pour les listes.
3. **Limites.**
   - Upload audio : 100 Mo (code du Worker).
   - Ligne D1 : environ 2 Mo.
   - Corps de requête Worker : 100 Mo.
   - Côté juridique : usage personnel, contenus que tu as le droit de transformer ; pas de contournement d'accès payant (règle déjà dans la v2.0).
4. **Adaptation demandée depuis la PWA, Mac éteint.** Demande différée seulement : une table `adaptation_requests`, lue par l'atelier à son ouverture, avec un statut visible dans la PWA. Aucune génération instantanée promise.
5. **Publication atomique.**
   - Aujourd'hui : audio puis contenu. Correct, sauf qu'un échec de `POST /content` laisse un audio orphelin.
   - Avec les clés versionnées : état `pending` jusqu'à l'activation, puis nettoyage à 24 h (v1.2, § 8.2).
6. **Modèles accessibles.**
   - Clés présentes : OpenAI, OpenRouter, Gemini, Groq, DeepSeek, xAI.
   - Modèles utilisés : `gemini-3.5-flash` et `deepseek-v4-flash` en majorité.
   - **Les crédits, quotas et règles de confidentialité ne sont pas vérifiables sans appels réels** : à confirmer par toi dans les consoles des fournisseurs avant de fixer les modèles du LOT 2.
7. **Format des chunks et cartes, déduplication.**
   - Une expression du SRS est une ligne `words` (`mot`, `type`, `niveau`, `traduction`, `examples` en JSON `[{en, fr}]`) plus une ligne `word_progress` par profil.
   - La déduplication actuelle (`promote-words`) compare `LOWER(mot)` uniquement.
   - **Proposition :** une forme normalisée (minuscules, apostrophes et espaces unifiés, ponctuation finale retirée) plus la catégorie, et l'**ajout d'un exemple** à la carte existante au lieu d'un doublon (v1.2, § 8.4).

---

## 7. Tests de non-régression ajoutés

| Dépôt | Branche locale | Fichiers | Tests | Ce qu'ils protègent |
|---|---|---|---|---|
| Worker | `chore/lot0-non-regression` | `test/support/env.ts` (D1 en mémoire sur les **vraies migrations**, R2 et Secrets Store simulés), `test/content.test.ts`, `test/audio.test.ts`, `test/apprentissage.test.ts`, `test/securite.test.ts`, `test/smoke.test.ts` | **43** | Aller-retour exact de la `metadata` de l'atelier ; republication sans doublon ni éviction ; isolation `default` / `__global__` ; favori et suppression (avec audio) ; upload et lecture audio ; SRS (stats, session, review, triage, known) avec les payloads de la PWA ; passerelle `promote-words` ; `learning_events` ; routes protégées ; failles documentées en `it.fails` |
| PWA | `chore/lot0-non-regression` | `src/api/learningApi.contract.test.ts` | **6** (22 au total) | Fusion `default` + `__global__` ; URL audio ; lecture d'un **ancien** contenu et d'un contenu v2 ; payload `/srs/review` ; tableau de bord ; suppression |
| Atelier | (pas de git) | `tests/test_contrat.py` | **5** (34 au total) | Champs du payload attendus par le Worker et la PWA, sources FR et EN ; règle de clé R2 ; routes du serveur local (page, bundles, détail, jobs, audio en Range 206) |

Commandes :

```bash
cd ~/mesProjects/myMobileProjects/englishfluency-worker && npm test
```

```bash
cd ~/mesProjects/myMobileProjects/englishPwa && npm test
```

```bash
cd ~/mesProjects/myMobileProjects/convert && python3 -m unittest discover -s tests
```

**Non couvert :**
- rendu des composants de la PWA (il faudrait ajouter jsdom) ;
- app React Native (plus utilisée) ;
- Live, qui ne passe pas par le Worker ;
- appels réels aux fournisseurs d'IA.

---

## 8. Conventions de versionnement (à appliquer dès le LOT 1)

| Identifiant | Définition | Format | Change quand… |
|---|---|---|---|
| `sourceRevision` | Empreinte de la source brute (octets de l'audio original, ou texte source normalisé en UTF-8) | 16 premiers caractères hexadécimaux du SHA-256 | La source elle-même change (rare : réimport) |
| `segmentationVersion` | Version du découpage en segments | Entier à partir de 1 | On re-segmente (nouveau SRT, nouveau découpage) |
| `audioRevision` | Empreinte du fichier audio publié | 8 premiers caractères hexadécimaux du SHA-256 des octets | L'audio est régénéré (Kokoro) ou remplacé |
| `contentRevision` | Empreinte de ce qui est publié pour une variante : textes EN/FR, pédagogie, `segmentationVersion`, `audioRevision` | 16 caractères hexadécimaux | N'importe lequel de ces éléments change |
| `variantId` | Identifiant stable d'une variante | `<contentId>~<kind>[~<niveau>]`, par ex. `cyber~faithful`, `cyber~adapted~B1` | Jamais (une nouvelle variante a un nouvel id) |
| Clé R2 audio | Fichier immuable | `prepared-content/<contentId>-<kind>-<audioRevision>.mp3` (les anciennes clés restent lisibles) | Jamais réécrite : nouvelle révision = nouvelle clé |
| Référence externe | Lien vers un segment depuis une séance, une carte SRS ou une annotation | `{ contentId, variantId, contentRevision, segmentationVersion, segmentId }` | Figée au moment où elle est créée |
| Identifiants internes | Segments, chunks, grammaire, séances | `s001`, `c001`, `g001` ; séance = UUID v4 généré par la PWA | Les ids `sNNN` ne valent que pour une `segmentationVersion` donnée |

Dans l'atelier, `contentRevision` est déjà calculé (`pipeline.revision_contenu`). Il faudra simplement y remplacer la taille de l'audio par `audioRevision` et y ajouter `segmentationVersion`.

---

## 9. Avant de lancer le LOT 1

À décider ou à faire, dans cet ordre :

1. ✅ ~~Corriger la faille du proxy IA et des TTS~~ (§ 3.1) : fait et déployé.
2. **Changer le secret du Worker** (§ 3.2), puis **protéger les lectures GET** (§ 3.3).
3. **Committer** `srs.ts` et `learning.ts` dans le Worker (code déjà en production).
4. **Mettre `convert/` sous git**, avec un `.gitignore` pour `fileToImport/`, `venv-tts/`, `modeles_tts/`, `_sauvegardes/` et `config_import.json`.
5. Puis LOT 1, en commençant par la liste `/content` allégée (§ 5.1) et les fondations audio (Range, clés versionnées, références).
