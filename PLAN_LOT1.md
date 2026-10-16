# Plan LOT 1 — Sources multiples + fondations audio

**Date :** 16 octobre 2026
**Références :** cahier v2.0 § 11 (LOT 1), détails d'écoute active v1.2 (§ 6.1, 6.4, 6.5, 8.1, 8.2), `AUDIT_LOT0.md` § 8 (conventions) et § 9.
**Base de départ vérifiée :** Worker 99 tests, PWA 22, atelier 46, tous verts.

**Hors LOT 1** (v2.0) : séances d'écoute active, lecteur segmenté `requestAnimationFrame`, `promote-chunks`, questions et connected speech (LOT 3) ; profil lexical (LOT 2) ; adaptations et `content_variants` (LOT 4).

Chaque étape : tests d'abord, puis code, puis les trois suites. Aucun déploiement ni push sans ton accord.

---

## Étape 0 — Préalables (audit § 9)

- 0.1 ✅ Git configuré par toi (`main`, remote `bricebrain/atelierConvert`). Ajoutés : `.gitignore` (`fileToImport/` **jamais versionné**, `venv-tts/`, `modeles_tts/`, `_sauvegardes/`, `config_import.json`, `__pycache__/`, `.DS_Store`) et `config_import.example.json` sans secret. Reste : commit de l'état actuel (sans push).
- 0.2 Branches de travail : Worker `feat/lot1` depuis `fix/auth-get-reads` ; PWA `feat/lot1` depuis `chore/lot0-non-regression`. Tes fichiers non commités du Worker (`src/srs.ts`, `src/learning.ts`) restent tels quels, jamais inclus dans mes commits.

## Étape 1 — Liste `/content` allégée (Worker + PWA)

**Worker**
- `GET /content?…&view=summary` : `metadata` réduite à un résumé (champs scalaires : `schemaVersion`, `sourceType`, `sourceLanguage`, `audioOrigin`, `contentRevision`, `segmentationVersion`, `timingSource`, `durationLabel`, `durationSeconds`, `wordsPerMinute`…) + compteurs `segmentCount`, `chunkCount`, `grammarPointCount`, `hasTimings`, et un `excerpt` (≈ 300 caractères) pour l'aperçu. `body` tronqué.
- Sans `view` : réponse **inchangée** (rétrocompatibilité ; on pourra basculer le défaut plus tard).
- Nouveau `GET /content/:id` (authentifié) : contenu complet.
- Tests : taille de la liste, compteurs, ancien contenu, `__global__`, 404, 401.

**PWA**
- `getPreparedContent` passe en `view=summary` ; la carte charge le détail (`GET /content/:id`, React Query) à l'ouverture d'un panneau Bilingue / Chunks / Grammaire / Script.
- Les compteurs des boutons viennent du résumé. Tests du mapping résumé → `PreparedContent` et du chargement du détail.

## Étape 2 — Range et cache sur `/audio/*` (Worker)

- `bytes=a-b`, `bytes=a-`, `bytes=-n` → `206` + `Content-Range`, `Content-Length`, `Accept-Ranges: bytes`, lecture partielle R2 (`range` de `get`). Plage invalide → `416` + `Content-Range: bytes */<taille>`. Sans Range : 200 comme aujourd'hui (+ `Accept-Ranges`, `Content-Length`).
- `HEAD /audio/*` (aujourd'hui non routé).
- `Cache-Control: immutable` **seulement** pour les clés versionnées (et le cache TTS par empreinte) ; les anciennes clés fixes `prepared-content/<id>.mp3` passent en cache court revalidé.
- Le simulateur R2 des tests gagne la lecture partielle. Tests : les trois formes, fin incluse, 416, HEAD, ancienne clé, type MIME.

## Étape 3 — Références audio et cycle de vie (Worker)

- Migration `0015_audio_references.sql` : `key`, `content_id`, `kind` (`content` | `srs_card` | `transfer`), `ref_id`, `state` (`pending` | `active` | `retired`), `created_at`, `updated_at`, `retired_at`. **Reprise des contenus existants** : une référence `active` pour chaque `audio_r2_key` en `prepared-content/`.
- `POST /content/audio?key=…&contentId=…` : la clé doit commencer par `prepared-content/<contentId>-` (sinon 400) ; enregistrée en `pending`. Sans `contentId` (ancien atelier) : comportement actuel, sans référence.
- `POST /content` : dans **un seul batch D1**, la nouvelle clé passe `active` et l'ancienne clé du contenu (si elle change) passe `retired`. Proposition : retrait côté Worker plutôt que par un second appel de l'atelier → pas d'état intermédiaire si l'atelier plante entre deux requêtes.
- `POST /content/audio/retire` `{contentId, key}` (v1.2 § 8.2) : 403 si la clé appartient à un autre contenu, 409 si c'est la clé active, 400 hors `prepared-content/`.
- `DELETE /content/:id` : **ne supprime plus l'audio dans R2** ; les références `content` passent `retired`, les `srs_card` restent.
- Éviction du 51e contenu : même traitement (plus d'audio orphelin).
- Tâche de nuit (ajoutée au cron existant) : supprime de R2 les `pending` de plus de 24 h et les `retired` de plus de 7 jours **sans aucune** référence `srs_card` ni `transfer` active ; uniquement sous `prepared-content/`.
- Tests : EA-06, EA-07, EA-19, EA-20, EA-21 (la création de cartes `srs_card` arrive au LOT 3 ; le test insère la référence directement).

## Étape 4 — Horodatage et versions (atelier)

- **Conventions** (`pipeline.py`) : `sourceRevision` (16 hex), `audioRevision` (8 hex des octets), `segmentationVersion` (entier dans `segments.json`), `contentRevision` = textes + pédagogie + `segmentationVersion` + `audioRevision` (remplace la taille de l'audio), `variantId = <id>~faithful`.
- **EN, audio authentique** : MacWhisper en `--format srt` ; `<slug>.transcript.en.srt` conservé, `.txt` dérivé. Segments = répliques consécutives regroupées (≈ 220 caractères, jamais une réplique coupée), `startMs`/`endMs` du SRT, `timingSource: macwhisper_srt`. Les sous-titres YouTube restent sans horodatage (`timingSource: null`).
- **FR → Kokoro EN** : `tts_kokoro.py` synthétise **segment par segment** (blocs internes si long), écrit `<slug>.audio-en.timings.json` `[{id, startMs, endMs}]` calculé sur les échantillons et silences, avec l'empreinte du texte EN ; obsolète avec l'audio (mécanisme existant). `timingSource: kokoro`.
- **Contrôles** : croissance, chevauchement ≤ 200 ms, fin ≤ durée + 500 ms. Invalide → publiable, `timingStatus: invalid`, timings non publiés (pas d'écoute active).
- `wordsPerMinute` par segment et global.
- Action « Horodater » sur un ancien bundle déjà traduit : avertissement (traduction et analyse à refaire), `segmentationVersion` + 1.
- **Publication** : clé `prepared-content/<id>-faithful-<audioRevision>.mp3`, upload avec `contentId`, metadata enrichie (`segmentationVersion`, `timingSource`, `timingStatus`, `audioRevision`, `variantId`, `sourceRevision`, `wordsPerMinute`). Plus aucune réécriture d'une clé existante.
- Interface : badge « Horodaté » / « Sans horodatage », ▶ par segment dans le tableau bilingue pour vérifier l'alignement à l'oreille.
- Tests : regroupement SRT (frontières, ordre, ms), parse SRT, timings Kokoro (calcul sur échantillons simulés, sans charger le modèle), contrôles, empreintes, nom de clé, payload.

## Étape 5 — Import texte (atelier)

- Nouvel import : texte collé, fichier `.txt` / `.md` (Markdown nettoyé en texte), article collé (URL, auteur, date facultatifs, comme **provenance** seulement), transcription personnelle.
- Formulaire : titre éditable, type `article | transcript | personal_output | other`, langue **proposée** (heuristique locale simple, sans dépendance) puis confirmée, aperçu caractères / paragraphes, limite de taille.
- Bundle : `<slug>.source.<langue>.txt` immuable + `sourceRevision` ; `meta.sourceType` `pasted_text` | `article_url` | `personal_transcript`. Segmentation par paragraphes puis phrases, ids stables `s001…`, timings `null`.
- Suite inchangée : traduction fidèle par le prompt copier-coller existant (FR → EN ou EN → FR), analyse pédagogique, publication **sans audio** (`audioR2Key: null`, `audioOrigin: null`).
- Kokoro **facultatif** pour un texte (EN source ou EN traduit) : bouton « Générer l'audio », mêmes timings que l'étape 4.
- Production personnelle : le brut est conservé tel quel ; la correction EN annotée (distincte d'une reformulation) est un prompt copier-coller dédié, stocké à part (`<slug>.correction.en.json`), et devient le texte EN de référence. *(À confirmer, voir questions.)*
- Tests : EF-01, EF-02, EF-03, EF-06 côté atelier ; normalisation `.md` ; détection de langue ; segmentation paragraphes ; payload sans audio.

## Étape 6 — Lecteur source / texte / audio (PWA)

- Carte d'un contenu **sans audio** : pas de lecteur, lecture du texte et du bilingue intacte, mention « Texte seul » (EF-06, EF-26).
- Badge `Voix authentique` / `Kokoro — voix de synthèse`, type de source (vidéo, article, texte, production personnelle) et lien de provenance s'il existe.
- Contenu horodaté : surlignage du segment en cours via `timeupdate` (simple ; la boucle segmentée est au LOT 3).
- Écoute libre et anciens contenus inchangés. Tests des helpers (`hasContentAudio`, badges, source) et du contrat résumé/détail.

## Étape 7 — Recette et bilan

- Les trois suites + `npm run build` PWA + `wrangler deploy --dry-run`.
- Republier depuis l'atelier les 2 contenus v2 et la CAN (audio français à remplacer) **après** ton accord de déploiement.
- Recette Safari iPhone (EA-05/EF-15) à faire par toi : je fournis la liste des vérifications.
- Bilan technique de fin de lot dans `AUDIT_LOT0.md` ou un `BILAN_LOT1.md`.

**Ordre de déploiement (le moment venu, avec ton accord) :** Worker (étapes 1–3, rétrocompatibles) → PWA → atelier republie.
