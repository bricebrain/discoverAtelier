# Bilan LOT 1 — Sources multiples + fondations audio

**Date :** 16 octobre 2026
**Plan suivi :** `PLAN_LOT1.md` (validé avec les choix recommandés).
**Worker déployé le 16/10/2026** (avec ton accord) : version `58b464c4` (`feat/lot1`, commit `190ebcc`, plus `src/srs.ts` et `src/learning.ts` non commités, déjà en production auparavant). **PWA non poussée, atelier non publié.** Le reste est commité en local sur les branches `feat/lot1`.

### Déploiement du Worker
- **Retour arrière :**
  - Worker : `wrangler rollback 1bd5c192-e123-4895-b55b-dd9419944691` ;
  - D1, avant la migration : `wrangler d1 time-travel restore englishfluency --bookmark=0000021b-00000000-00005106-ee2a5e1da818d8dd8be8e0a6113c411c`.
- **Migration 0015 :** appliquée seule (`d1 execute --file`). Elle a créé 4 références `active`, une par audio de l'atelier publié. Elle n'est pas inscrite dans `d1_migrations` ; elle est idempotente, donc un futur `migrations apply` la rejouera sans effet.
- **Migration 0014 (`fix_glued_translations`)** : appliquée ensuite avec ton accord, via `wrangler d1 migrations apply --remote`, qui a aussi inscrit 0015 (rejouée sans effet : toujours 4 références). Signet de restauration pris avant : `00000220-00000000-00005106-947d6fb4c0c0d54023da6f6f100c4080`. Vérifié :
  - « demander (à) », « dire (à) », « douze », « rendre », « nourrir, donner à manger à » ;
  - cartes Lingvist resynchronisées (`ask_0036` → « demander (à) ») ;
  - plus aucune traduction collée : les 5 correspondances restantes sont légitimes (« déjà », « là »).
- **Vérifié en production :**
  - santé 200 ; lectures et proxy toujours 401 sans secret ;
  - liste complète inchangée (segments présents) ;
  - **liste résumée du profil : 9,9 Ko au lieu de 258 Ko**. Pour `__global__`, le gain est nul (51 Ko contre 50 Ko : corps JSON structurés, déjà courts) ;
  - `GET /content/:id` identique à la liste complète ; 404 et 401 corrects ;
  - audio : Range `0-1` et suffixe → 206, plage invalide → 416, `HEAD` sans corps, 200 sans Range ; ancienne clé fixe servie en `max-age=3600, must-revalidate` ;
  - `retire` : 409 sur la clé active, 403 sur la clé d'un autre contenu.

## 1. Résultat

| Dépôt | Tests avant | Tests après | Commits (`feat/lot1`) |
|---|---|---|---|
| Worker | 99 | **158** | `d0fef97`, `5a94ea1`, `e31abf9`, `190ebcc` |
| PWA | 22 | **33** | `7d306f8`, `198f274` |
| Atelier | 46 | **96** | `167c3c7` (version initiale), `fa0223f`, `cfecee1` |

Vérifications en plus des tests :
- PWA : `tsc`, `eslint` et `npm run build` passent.
- Worker : `wrangler deploy --dry-run` passe. La migration `0015` est appliquée sans erreur sur une D1 locale.
- **Recette de bout en bout en local** (Worker `wrangler dev --local`, PWA branchée dessus, atelier sur un dossier de bundles de test) :
  - publication de 3 contenus (vidéo EN horodatée par SRT, article EN avec **vraie synthèse Kokoro segment par segment**, production personnelle sans audio) ;
  - liste résumée, `206` / `416`, cache `immutable` sur les clés versionnées, références audio créées ;
  - PWA mobile : badges, « Texte seul », détail chargé à l'ouverture, segment surligné pendant la lecture, positionnement en touchant un segment.
- Kokoro réel : le dernier segment finit à 14,97 s pour une piste de 15,38 s, ce qui est cohérent (0,35 s de silence final + latence de l'encodeur MP3).

## 2. Ce qui a été livré

### Worker
- `GET /content?view=summary` : la `metadata` est réduite aux champs scalaires, les textes longs sont tronqués à 500 caractères (liste dans `summary.truncatedKeys`), et des compteurs remplacent les tableaux. **Sans `view`, la réponse est inchangée.**
- `GET /content/:id` : renvoie le contenu complet (authentifié).
- `GET|HEAD /audio/*` :
  - `Range` `a-b`, `a-` et `-n` → `206` ; plage invalide → `416` ;
  - lecture partielle dans R2 ;
  - `immutable` seulement pour les clés versionnées et le cache TTS (les anciennes clés fixes passent en cache court).
- Migration `0015_audio_references.sql`, avec reprise des audios déjà publiés.
- Cycle de vie (v1.2 § 8.2) :
  - un upload avec `contentId` crée une référence `pending` ;
  - `POST /content` active la nouvelle clé et retire l'ancienne dans **un seul batch D1** ;
  - la suppression ou l'éviction d'un contenu ne supprime plus l'audio dans R2 ;
  - `POST /content/audio/retire` répond 403, 409 ou 400 selon les cas ;
  - le cron de nuit nettoie les clés `pending` après 24 h et `retired` après 7 j, jamais tant qu'il reste une référence `srs_card` ou `transfer`.

### Atelier
- **Versions :**
  - `sourceRevision`, `audioRevision`, `segmentationVersion`, `variantId` (`<id>~faithful`) ;
  - `contentRevision` inclut désormais l'empreinte de l'audio et les timings publiés ;
  - clé immuable `prepared-content/<id>-faithful-<audioRevision>.mp3`.
- **EN :** MacWhisper en SRT (le `.srt` est conservé, le `.txt` en est dérivé). Les segments sont des répliques regroupées (≈ 220 caractères, sans couper une réplique).
- **FR → EN :** Kokoro synthétise segment par segment et écrit `<slug>.audio-en.timings.json`. Ces timings deviennent obsolètes si le texte anglais change.
- **Contrôles :** timings croissants, chevauchement ≤ 200 ms, fin ≤ durée + 500 ms. Un horodatage invalide laisse le contenu publiable, mais sans timings. Le débit (mots par minute) est calculé par segment et sur l'ensemble.
- **Interface :**
  - badge « Horodaté / Sans horodatage / invalide » ;
  - ▶ par segment (marge de 120 ms, arrêt par `requestAnimationFrame` ; mesuré : arrêt à 8 ms de la cible) ;
  - action « Horodater » avec avertissement. Les anciens segments et l'analyse sont sauvegardés en `.v<n>.bak.json`.
- **Import texte :**
  - texte collé, `.txt`, `.md`, article collé (URL, auteur et date comme provenance), production personnelle ;
  - langue proposée puis confirmée ;
  - source brute conservée telle quelle ;
  - segmentation par paragraphes ;
  - publication **sans audio** ; Kokoro facultatif.
- **Production personnelle EN :**
  - la correction passe par un prompt copier-coller, stockée dans `<slug>.correction.en.json` ;
  - le texte corrigé devient la référence ;
  - le brut est publié à part dans `personalOriginalText`, pas dans `originalText`, que la PWA lit comme une traduction française.

### PWA
- La liste se charge en vue résumée ; le détail est chargé à l'ouverture d'un panneau.
- Badges « Voix authentique » / « Kokoro — voix de synthèse », type de source, lien « Voir la source » (http(s) seulement), « Texte seul ».
- Surlignage du segment en cours (`timeupdate`) ; toucher un segment positionne la lecture en cours.

## 3. Rétrocompatibilité et ordre de déploiement (à faire avec ton accord)

1. **Worker d'abord** : `wrangler d1 migrations apply englishfluency --remote`, puis `wrangler deploy`. Tout est additif, et l'ancienne PWA continue de fonctionner.
2. **PWA ensuite** (push). Si elle partait avant le Worker, elle resterait fonctionnelle : `view=summary` serait ignoré et la liste complète renvoyée, sans champ `summary`, donc aucun appel au détail.
3. **Republier depuis l'atelier en dernier.** Si l'atelier publie vers l'ancien Worker, les clés versionnées seraient écrites sans références, puis ignorées par le nettoyage. Ce ne serait pas grave, mais ce serait sale.

À la republication, les anciennes clés fixes (dont l'audio **français** de la CAN) passeront `retired` et seront supprimées 7 jours plus tard par le cron : aucune carte SRS ne les référence aujourd'hui.

Tous les contenus apparaîtront « non publiés » dans l'atelier, car la formule de `contentRevision` a changé. C'est voulu : republier les fait passer aux clés versionnées.

## 4. Pour les contenus existants

| Contenu | Pour obtenir l'horodatage |
|---|---|
| `comment-blackrock…` (FR) | Régénérer l'audio Kokoro : les timings sont produits, **sans retraduire** |
| `ai-designed-viruses…`, `wtf-is-happening-with-cybersecurity` (EN) | « Horodater » : MacWhisper en SRT (plusieurs minutes), puis **traduction et analyse à refaire** |
| `why-tech-stocks…`, `pourquoi-la-can…` (anciens imports) | Republier depuis l'atelier |

## 5. Limites et reste à faire

- **À tester sur iPhone (par toi) :** EA-05 / EF-15 (Range et positionnement sous Safari) et EA-02 (écart < 150 ms sur 10 segments Kokoro), à l'oreille.
- **Comparer à l'oreille la prosodie Kokoro segment par segment sur 2 contenus** (risque listé en v1.2 § 15.2). Le silence entre segments vaut 0,35 s (`tts_kokoro.SILENCE_ENTRE_SEGMENTS`).
- **Références `srs_card` :** elles sont prises en compte par le nettoyage, mais aucune route ne les crée encore (`promote-chunks`, LOT 3). Le retrait de la référence à la suppression d'une carte SRS sera à brancher en même temps (EA-21 est testé en insérant la référence directement).
- **Hors périmètre retenu :**
  - extraction automatique d'article depuis une URL ;
  - traduction par API (collage manuel seulement) ;
  - audio joint à une transcription personnelle ;
  - reformulation distincte de la correction ;
  - horodatage des sous-titres YouTube (seul MacWhisper produit des timings).
- **Cache :** les préfixes autres que `prepared-content/` et `tts/` (Assimil, podcasts…) restent en `immutable`, sans changement. Je n'ai pas vérifié s'ils sont réécrits.
- **PWA :** « Écouter en synthèse vocale » sur une carte résumée charge d'abord le détail ; sur iOS, le geste utilisateur peut se perdre la première fois (relancer suffit).
