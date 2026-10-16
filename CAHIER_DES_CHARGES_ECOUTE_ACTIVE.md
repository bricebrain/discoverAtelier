# Cahier des charges — Écoute active (atelier, Worker, PWA)

**Version :** 1.2 — 16 octobre 2026
**Statut :** prête pour le lot 1
**Projets concernés :**
- `convert/` — atelier de préparation (Python, application Mac locale)
- `englishfluency-worker/` — API Cloudflare (Worker, D1, R2)
- `englishPwa/` — application d'apprentissage (React, TypeScript, MUI)

**Documents liés :**
- `Analyse méthode écoute anglais.pdf` — analyse de la méthode LindseyLingo et du Comprehensible Input (source de ce cahier).
- Revue de la version 1.0 (`~/Downloads/Analyse méthode écoute anglais.pdf`) et revue de la version 1.1 (`~/Downloads/Analyse méthode écoute anglais (1).pdf`), dont les remarques sont intégrées ici.
- `CAHIER_DES_CHARGES_ENGLISH_FLUENCY_STUDIO.md` — pipeline bilingue de l'atelier, déjà implémenté.

**Principe directeur :** faire de l'écoute une compétence qu'on entraîne avec méthode, sans transformer chaque podcast en examen, **et observer honnêtement si cela semble améliorer la compréhension orale**. L'écoute libre (extensive) reste l'usage principal. L'écoute active (intensive) s'y ajoute, sur des extraits courts.

---

## 0. Changements

### 0.1 Depuis la version 1.1

| Remarque de la revue | Correction apportée | Section |
|---|---|---|
| Le protocole a trop peu de questions : quelques réponses au hasard suffisent à franchir le seuil | 12 à 16 extraits de contrôle visés (8 acceptés en mode exploratoire), 3 questions indépendantes à 4 choix, évaluation qualitative ajoutée, seuils présentés comme des repères | § 11 |
| « Prouver ou infirmer » est trop fort sans groupe de comparaison | « Observer si la méthode semble améliorer la compréhension et mérite d'être poursuivie » | § 2.1, § 11 |
| Les tests de transfert étaient préparés pour tous les chunks | Préparés pour **5 expressions prioritaires** par contenu ; file « Transferts à préparer » pour les expressions retenues qui n'en ont pas | § 6.3, § 8.5 |
| Les trois tests différés ne mesurent pas la même compétence | Deux indicateurs distincts : **compréhension du sens** et **reconnaissance de la forme sonore** | § 9.4, § 10 |
| Rien n'était prévu quand l'expression existe déjà dans le SRS | Déduplication par expression normalisée ; ajout d'un exemple audio à la carte existante ; maîtrise écrite et maîtrise orale distinguées (lot 2) | § 8.4, § 14 |
| Le cycle de vie des références audio était flou, et la route de retrait trop permissive | Cycle de vie formalisé (cartes supprimées, publication partielle, contenus anciens) ; vérification de propriété côté Worker | § 8.2 |
| Risque d'adaptations trop « intelligentes » | Règles simples et observables : une seule mauvaise réponse ne déclenche rien | § 5.3 |
| L'écoute active ne doit pas devenir un module isolé | Nouvelle section sur la circulation des informations entre modules | § 9.9 |

### 0.2 Depuis la version 1.0

| Remarque de la revue | Correction apportée | Section |
|---|---|---|
| La vérification différée « reconnue / pas reconnue » mesure la confiance plus que la compréhension | Trois tests de compréhension (sens, nouvelle phrase, forme sonore) ; l'auto-évaluation devient un complément | § 9.4 |
| ChatGPT ne connaît pas la prononciation réelle de l'enregistrement | `heard` devient `possiblePronunciation` avec `verified: false` ; vérification à l'oreille facultative dans l'atelier | § 6.2 |
| L'indicateur « autonomie = segments non marqués » est artificiel | Supprimé comme mesure d'autonomie ; remplacé par la compréhension d'extraits inédits | § 10 |
| La vérification différée arrivait trop tard (lot 2) | Nouveau **lot 1 bis — Validation pédagogique**, avant le protocole de 28 jours | § 14 |
| Une carte SRS peut pointer vers un audio supprimé | Les audios encore référencés sont conservés ; nettoyage seulement quand plus rien ne les utilise | § 6.5, § 8.2 |
| Les `segmentId` peuvent changer après une nouvelle segmentation | Chaque référence porte la `contentRevision` ; les cartes SRS gardent un instantané autonome | § 6.1, § 8.4 |
| ±150 ms impossible à garantir avec `timeupdate` | Boucle `requestAnimationFrame` pendant la lecture d'un segment ; tolérance réaliste de ±250 ms sur Safari iOS | § 9.2 |
| La source des « autres voix » n'était pas définie (TTS du Worker) | Phrases de transfert générées par ChatGPT (manuel) et synthétisées par **Kokoro dans l'atelier**, avec une autre voix ; aucun service payant | § 6.3 |
| Le débit moyen sur tout l'audio est insuffisant | Débit calculé **par extrait**, et présenté comme un indice parmi d'autres | § 6.4 |
| Faute de frappe dans EA-01 (« SRS ») | « SRT » | § 13 |
| Parcours en cinq phases identique pour tous | Parcours de référence avec trois adaptations par règles simples | § 5.3 |
| Réponses aux quatre questions ouvertes | Décisions intégrées (extrait de 1 à 2 min, restitution locale, Kokoro signalé, 0 à 2 chunks) | § 15 |
| Le cahier dit comment construire, pas comment prouver | Nouvelle section : protocole de 28 jours et critères de réussite | § 11 |

---

## 1. Avis sur l'analyse

L'analyse est solide. Elle est surtout nuancée là où les vidéos de LindseyLingo exagèrent, et elle colle bien à l'écosystème existant.

### 1.1 Ce que je reprends tel quel

1. **Connaître l'anglais n'est pas comprendre l'oral.** Le blocage vient souvent de la reconnaissance des sons et du découpage des phrases, pas du vocabulaire.
2. **La routine en 5 temps** : écoute sans texte, décodage avec transcription, réécoute sans texte, restitution, mémorisation ciblée. L'écoute guidée a un effet mesuré (Vandergrift & Tafaghodtari, 2010). Les durées sont des repères.
3. **La connected speech** (réductions, liaisons, formes faibles) est un domaine d'entraînement reconnu (revue de 22 études).
4. **Le diagnostic à quatre causes** : vocabulaire, reconnaissance auditive, vitesse de traitement, sens global. Chaque cause appelle un entraînement différent.
5. **L'illusion de compréhension** : reconnaître une phrase entendue cinq fois ne prouve rien. Seule une vérification différée, sur une autre phrase et une autre voix, mesure le transfert.
6. **Mesurer la progression, pas l'activité.**

### 1.2 Mes nuances et mes choix

- **La voix de synthèse** ne doit pas devenir la seule source d'oral. L'écoute active est proposée en priorité sur les audios authentiques. Elle reste disponible sur Kokoro, avec la mention « voix de synthèse ».
- **Pas de quiz systématique** : 3 questions au plus, facultatives, uniquement pour mesurer la première écoute.
- **Pas d'API d'IA payante** : tout ce qui demande un modèle de langage passe par un prompt copié dans ChatGPT puis un JSON collé dans l'atelier. La restitution orale passe par ChatGPT Live.
- **Tester avant de tout construire** : les lots 1 et 1 bis suffisent à mener le protocole de 28 jours ; la suite dépend de ses résultats.
- **Pas de moteur pédagogique** en v1, seulement quelques règles simples et explicables.

---

## 2. Objectifs et périmètre

### 2.1 Objectifs

- Proposer, pour chaque contenu horodaté, une **séance d'écoute active** d'environ 15 minutes sur un extrait de 1 à 2 minutes.
- Permettre de **rejouer précisément chaque phrase**, avec la transcription synchronisée et la traduction à la demande.
- Recueillir un **diagnostic** sur les passages difficiles et y répondre par un entraînement adapté.
- Proposer **0 à 2 expressions** par séance pour le SRS, uniquement si elles en valent la peine.
- **Vérifier à J+3 et J+10** que l'expression est comprise dans une phrase et une voix nouvelles.
- **Observer** avec le protocole de 28 jours (§ 11) si la méthode semble améliorer la compréhension orale et mérite d'être poursuivie.

### 2.2 Hors périmètre

- Reconnaissance vocale de l'apprenant ou notation de sa prononciation.
- Génération automatique de contenus par IA côté serveur.
- Remplacement du SRS, de Lingvist, de la lecture ou de la séance Live existants.
- Moteur de recommandation entraîné sur des données.
- Analyse phonétique automatique de l'audio.

---

## 3. Principes à respecter dans toute l'implémentation

| Principe | Conséquence concrète |
|---|---|
| L'écoute libre reste première | Le lecteur actuel est conservé ; l'écoute active est un mode supplémentaire, jamais imposé. |
| Pas d'examen sur chaque contenu | 3 questions au plus, facultatives ; aucune note bloquante. |
| L'authentique avant la synthèse | Les audios Kokoro sont signalés ; les vidéos anglaises sont proposées en premier. |
| La répétition n'est pas la maîtrise | Une expression n'est jamais « acquise » après une séance ; seule la vérification différée compte. |
| Comprendre se mesure, se déclarer ne suffit pas | Toute auto-évaluation est accompagnée d'une question portant sur le sens. |
| Une prononciation théorique n'est pas une observation | Les annotations de connected speech sont « possibles » tant qu'elles n'ont pas été vérifiées à l'oreille. |
| Ne pas forcer la mémorisation | Une expression n'entre dans le SRS que si elle est utile, nouvelle ou difficile ; on peut n'en retenir aucune. |
| Les références sont versionnées | Séances, annotations et cartes SRS mentionnent la version du contenu ; un audio référencé n'est jamais supprimé. |
| Mesurer la progression | Les statistiques n'affichent ni minutes écoutées ni compteurs d'activité. |
| ChatGPT reste manuel | Prompt copié, JSON collé et validé dans l'atelier. |

---

## 4. Existant et prérequis (constats vérifiés le 16/10/2026)

### 4.1 Atelier (`convert/`)

- Les segments (`<slug>.segments.json`) ont des champs `startMs` / `endMs`, **toujours à `null`** aujourd'hui.
- La transcription passe par MacWhisper en format `txt`. **Testé :** `mw transcribe --format srt` fournit l'horodatage de chaque réplique. Le format `json` exige une licence MacWhisper Pro.
- Kokoro (`tts_kokoro.py`) synthétise par blocs d'environ 300 caractères, avec 0,15 s de silence entre les blocs. La durée de chaque bloc est connue à la génération. Six voix sont installées (4 britanniques, 2 américaines).
- La publication envoie `metadata.segments`, `chunks`, `grammarPoints`, `textEn`, `textFr`, `durationLabel`, `audioOrigin` et `contentRevision`.
- L'audio publié utilise une clé R2 fixe : `prepared-content/<id>-en.mp3` (source FR) ou `prepared-content/<id>.mp3` (source EN).

### 4.2 Worker (`englishfluency-worker/`)

- `GET /audio/<clé>` sert les fichiers R2 **sans requêtes Range** (pas de 206). Safari iOS en a besoin pour se positionner dans un audio : **prérequis bloquant**.
- Cette route renvoie `Cache-Control: … immutable`, alors que la clé ne change pas quand l'audio est régénéré.
- Le SRS repose sur `words` + `word_progress`. Les passerelles `POST /articles/promote-words` et `POST /podcasts/promote-words` créent le mot s'il manque et le rendent dû immédiatement.
- La table `learning_events` journalise les activités (module `listen`).
- `POST /content` accepte une `metadata` JSON libre.
- Une tâche planifiée tourne chaque nuit (`17 3 * * *`).

### 4.3 PWA (`englishPwa/`)

- `useAudioPlayer` gère la lecture, le positionnement, la vitesse et l'événement `timeupdate`.
- `PreparedContentCard` affiche déjà la lecture bilingue, les chunks et la grammaire.
- La page Live copie un prompt pour ChatGPT Live et garde le bilan en local.
- La PWA est en thème clair et en mode portrait : l'écoute active se conçoit **pour le téléphone**.

---

## 5. La séance d'écoute active

### 5.1 Point d'entrée et extrait

- Sur la fiche d'un contenu horodaté : bouton **« Écoute active »** à côté du lecteur habituel.
- **Extrait** : une suite de segments consécutifs.
  - Longueur par défaut : **1 à 2 minutes** pour un contenu A2/B1 ;
  - jusqu'à **3 minutes** si le contenu est jugé accessible (§ 9.7).
- Par défaut, c'est le premier extrait pas encore travaillé. L'apprenant peut en choisir un autre dans la liste (« Extrait 2 · 1:50–3:40 », avec son débit).

### 5.2 Le parcours de référence en cinq phases

Une barre montre les phases. Leurs durées sont indicatives, rien n'est chronométré de façon bloquante.

**Phase 1 — Écoute sans transcription**
- L'extrait est joué sans texte.
- Auto-évaluation : *Presque rien* / *Le sujet* / *Les idées principales* / *Presque tout*.
- **Au moins une question portant sur le sens** quand le contenu en a pour cet extrait (3 au plus, QCM en français). C'est elle qui mesure ; l'auto-évaluation la complète.

**Phase 2 — Décodage avec transcription**
- Transcription anglaise segment par segment, avec le segment en cours surligné.
- Toucher un segment le rejoue seul ; bouton « en boucle » ; vitesses 0,75×, 0,9×, 1×.
- Le français de chaque segment est masqué ; un bouton par segment l'affiche.
- L'apprenant marque **les segments qu'il n'a pas compris** (aucun minimum imposé, 5 au plus), avec la raison :
  1. Je connais les mots, mais je ne les ai pas reconnus à l'oral.
  2. Je ne connaissais pas certains mots ou expressions.
  3. J'ai reconnu les mots, mais je n'ai pas suivi assez vite.
  4. J'ai compris les mots, mais pas le sens général.
- Chaque segment marqué affiche l'aide adaptée à sa raison (§ 7).

**Phase 3 — Réécoute sans texte**
- L'extrait est rejoué en entier, sans texte.
- Pour chaque segment marqué : *Reconnu* / *En partie* / *Non*.

**Phase 4 — Restitution**
- Consigne : « Résume à voix haute ce que tu viens d'entendre, en anglais si possible. »
- Une note facultative reste **sur le téléphone uniquement**.
- Le bouton « Continuer avec ChatGPT Live » copie un prompt avec le titre, le texte anglais de l'extrait et la consigne de faire reformuler puis de poser 2 questions.

**Phase 5 — Mémorisation ciblée**
- L'écran propose les chunks des segments marqués, en premier ceux qui correspondent à la raison 2.
- Il présélectionne **au plus 2** expressions et permet de **n'en retenir aucune**.
- Il indique pourquoi chaque expression est proposée : « nouvelle pour toi », « déjà dans tes révisions », « non reconnue à l'oral ». Les expressions déjà connues de l'apprenant (déjà dans le SRS avec un bon niveau) ne sont pas présélectionnées.
- Fin de séance : récapitulatif, puis enregistrement dans le Worker.

### 5.3 Adaptations du parcours (règles simples)

Les cinq phases sont le parcours **de référence**. Trois règles l'adaptent, à partir de la phase 1 :

| Situation après la phase 1 | Adaptation |
|---|---|
| *Presque tout* **et** question(s) réussie(s) | Proposer de **terminer rapidement** : phase 2 facultative, puis directement la phase 5 ; ou passer à un extrait plus rapide du même contenu. |
| *Les idées principales* ou mieux, **mais** au moins 2 segments marqués pour la raison 1 | **Séance orientée décodage** : boucles audio, notes de connected speech et reconnaissance en premier ; la restitution devient facultative. |
| Auto-évaluation *Presque rien* ou *Le sujet* **et** question ratée (ou *Presque rien* si l'extrait n'a pas de question) | **Accompagnement renforcé** : extrait raccourci à environ 1 minute, vitesse 0,9×, transcription puis français disponibles dès la phase 2. |

Règles complémentaires, volontairement simples et observables :
- **Une seule mauvaise réponse ne déclenche jamais rien** à elle seule : il faut toujours la combinaison décrite ci-dessus.
- La suggestion « choisir un contenu plus accessible » n'apparaît qu'après **deux séances consécutives** en accompagnement renforcé sur le même contenu.
- Les adaptations sont des **propositions** affichées avec leur raison. L'apprenant peut toujours suivre le parcours complet.
- Aucune règle n'est ajoutée au-delà de ce tableau avant le bilan du protocole (§ 11).

### 5.4 Reprise

Une séance interrompue est gardée en local et reprend à la phase où elle s'était arrêtée. Une séance non terminée au bout de 24 h est abandonnée et n'est pas comptée.

---

## 6. Atelier (`convert/`) — exigences

### 6.1 Horodatage et version des segments

**Source anglaise (audio authentique)**
- MacWhisper transcrit au **format SRT**. Le fichier `<slug>.transcript.en.srt` est conservé ; le `.txt` en est dérivé.
- Les segments sont formés en regroupant des répliques SRT consécutives (≈ 220 caractères, sans couper une réplique) :
  - `startMs` = début de la première réplique ;
  - `endMs` = fin de la dernière.

**Source française (audio Kokoro)**
- Les timings de l'audio français ne sont **jamais** réutilisés.
- `tts_kokoro.py` synthétise **segment par segment** (un segment long est découpé en blocs internes). Il écrit un fichier de timings `[{id, startMs, endMs}]`, calculé à partir des échantillons générés et des silences insérés.
- Ces timings deviennent obsolètes en même temps que l'audio (mécanisme d'empreinte existant).

**Version des segments**
- `segments.json` reçoit :
  - `timingSource` : `macwhisper_srt` | `kokoro` | `null` ;
  - `segmentationVersion` : entier, incrémenté à chaque re-segmentation.
- Toute référence à un segment hors du bundle (annotations publiées, séances, cartes SRS) est accompagnée de la `contentRevision` du contenu publié.
- **Re-segmenter un contenu déjà traduit** (action « Horodater » sur un ancien bundle) oblige à refaire traduction et analyse. L'action affiche cet avertissement avant de démarrer.

**Contrôles avant publication**
- Timings croissants, pas de chevauchement de plus de 200 ms, fin du dernier segment ≤ durée de l'audio + 500 ms.
- Un horodatage invalide laisse le contenu publiable, mais **sans écoute active**.

### 6.2 Analyse pédagogique enrichie

Le prompt d'analyse (§ 6.4 du cahier Studio) est étendu avec deux sections.

**Connected speech : des prononciations possibles, pas des observations**

ChatGPT ne reçoit que le texte. Il peut indiquer une prononciation **fréquente**, pas celle que le locuteur a réellement utilisée. Le format est donc :

```json
{
  "connectedSpeech": [
    {
      "written": "should have told you",
      "possiblePronunciation": "shoulda told ya",
      "phenomenon": "reduction",
      "explanationFr": "À l'oral, « have » se réduit souvent en « a » après un modal, et « you » en « ya ».",
      "sourceSegmentId": "s004",
      "verified": false
    }
  ]
}
```

- Le prompt demande des prononciations **fréquentes en anglais britannique courant** et interdit d'affirmer ce que dit l'enregistrement.
- L'application force `verified: false` à l'import, quelle que soit la valeur collée.
- **Vérification à l'oreille, facultative** : dans l'étape Analyse, chaque annotation a un bouton ▶ qui rejoue son segment, et une case « Entendu dans l'audio ». Si on la coche, `verified` passe à `true`. C'est la seule façon de passer à `true`.
- Partout, la PWA formule une annotation non vérifiée comme **« Souvent prononcé… »**, et une annotation vérifiée comme **« Ici, on entend… »**.
- `phenomenon` ∈ `reduction`, `linking`, `elision`, `weak_form`, `assimilation`.

**Questions de compréhension (sens général)**

```json
{
  "comprehensionQuestions": [
    {
      "questionFr": "Quel est le sujet principal de ce passage ?",
      "choicesFr": ["Une cyberattaque", "Un rachat d'entreprise", "Une élection"],
      "answerIndex": 1,
      "segmentIds": ["s001", "s002"]
    }
  ]
}
```

- 3 ou 4 choix ; `answerIndex` valide ; `segmentIds` existants et **consécutifs**, pour qu'une question se rattache à un extrait.
- Au plus **une question par tranche d'environ 2 minutes d'audio**. Elle porte sur le sujet, l'idée principale ou l'intention, jamais sur un détail lexical.
- Une liste vide est acceptée.

### 6.3 Éléments de transfert (pour la vérification différée)

C'est ce qui permet de mesurer, à J+3 et J+10, la compréhension dans un contexte nouveau.

**Pour quelles expressions ?**
- Pas pour tous les chunks : l'apprenant n'en retiendra que 0 à 2 par séance, et des tests préparés pour tous seraient presque tous inutiles.
- L'atelier présélectionne **5 expressions prioritaires** par contenu : d'abord les types `idiom`, `phrasal_verb` et `useful_expression`, puis le niveau le plus proche du niveau cible. On peut modifier la sélection, et en ajouter plus tard.
- **File « Transferts à préparer »** : quand une expression retenue dans la PWA n'a pas de test de transfert, le Worker l'inscrit dans une file (§ 8.5). L'atelier affiche cette file, et on y prépare les tests manquants avec le même prompt, avant l'échéance de J+3.

**Génération (manuelle, sans API)**
- Un troisième prompt, **« Prompt de transfert »**, est proposé après l'analyse, pour les expressions sélectionnées.
- Pour chaque expression, ChatGPT écrit :
  - une **nouvelle phrase** courte (contexte différent de celui du contenu) ;
  - une **question de sens** avec 4 choix ;
  - **4 propositions d'expressions** (la bonne et trois proches), pour le test de forme sonore.
- Le JSON collé est validé comme les autres :

```json
{
  "transferItems": [
    {
      "chunkId": "c002",
      "sentenceEn": "I completely forgot to send the report. It slipped my mind.",
      "meaningQuestionFr": "Que veut dire le locuteur ?",
      "meaningChoicesFr": ["Il a oublié", "Il l'a envoyé en retard", "Il a refusé", "Il l'a perdu"],
      "meaningAnswerIndex": 0,
      "formChoicesEn": ["it slipped my mind", "it crossed my mind", "it made my mind", "it's on my mind"],
      "formAnswerIndex": 0
    }
  ]
}
```

**Audio (Kokoro local, autre voix)**
- L'atelier synthétise chaque `sentenceEn` avec Kokoro, avec une **voix différente** :
  - pour une source anglaise, une voix britannique de genre opposé à celle du locuteur si on la connaît ;
  - pour une source Kokoro, une autre voix que celle utilisée pour le contenu.
- Les fichiers sont publiés avec le contenu sous `prepared-content/<id>-transfer-<chunkId>-<révision>.mp3`.
- Aucun service de synthèse distant n'est ajouté.

**Limite assumée :** ces phrases sont en voix de synthèse. Le test mesure la compréhension dans une phrase et une voix nouvelles, pas face à un locuteur authentique. C'est noté dans les statistiques.

### 6.4 Débit par extrait

- L'atelier calcule `wordsPerMinute` **pour chaque segment** à partir des timings, et pour l'ensemble du contenu.
- La PWA en déduit le débit de chaque extrait, qu'elle affiche dans la liste des extraits.
- Le débit est un **indice parmi d'autres** : il ne mesure ni le vocabulaire, ni l'accent, ni la densité d'idées.

### 6.5 Audio versionné, sans perte de référence

- La clé publiée devient `prepared-content/<id>-<révision courte>.mp3` (8 premiers caractères de `contentRevision`).
- **L'atelier ne supprime jamais directement un ancien audio.** Après une publication réussie, il signale au Worker les anciennes clés devenues « candidates au nettoyage » (§ 8.2).

### 6.6 Interface de l'atelier

- Badge « Horodaté » / « Sans horodatage ».
- Tableau bilingue : bouton ▶ par segment pour contrôler l'alignement à l'oreille.
- Étape Analyse :
  - cartes « Connected speech », avec ▶ et la case « Entendu dans l'audio » ;
  - cartes « Questions de compréhension ».
- Nouvelle étape facultative « Transfert », entre Analyse et Audio : prompt, collage et génération des audios.

---

## 7. Diagnostic et entraînement associé

| Raison déclarée | Hypothèse | Entraînement proposé immédiatement | Proposé pour le SRS |
|---|---|---|---|
| 1. Mots connus, non reconnus à l'oral | **Décodage sonore** | Notes de connected speech du segment (« souvent prononcé » / « ici, on entend »), boucle à 0,75× puis 1× | L'extrait, en reconnaissance auditive |
| 2. Mots ou expressions inconnus | **Vocabulaire** | Chunks et traduction du segment | Le chunk, s'il est nouveau ou utile |
| 3. Reconnus, mais trop rapide | **Vitesse de traitement** | Réécoute à 0,75×, 0,9× puis 1× ; enchaînement avec le segment suivant | L'extrait, à réécouter à vitesse normale |
| 4. Mots compris, pas le sens | **Compréhension globale** | Traduction du segment et des segments voisins ; point de grammaire lié s'il existe | Rien d'automatique |

Une raison qui revient (plus de 60 % des marquages sur 7 jours) est signalée dans les statistiques comme « obstacle principal du moment ».

---

## 8. Worker (`englishfluency-worker/`) — exigences

### 8.1 Requêtes Range sur `/audio/<clé>` — lot 1, bloquant

- Gérer `bytes=a-b`, `bytes=a-` et `bytes=-n`. Répondre `206` avec `Content-Range`, `Accept-Ranges: bytes` et `Content-Length` justes, en ne lisant dans R2 que la plage demandée.
- Plage invalide : réponse `416` avec `Content-Range: bytes */<taille>`.
- Sans `Range` : comportement actuel inchangé.

### 8.2 Versions audio et nettoyage contrôlé — lot 1

- `Cache-Control: immutable` est conservé : il devient correct avec des clés versionnées.
- Nouvelle table `audio_references` : `key`, `content_id` (propriétaire), `kind` (`content` | `srs_card` | `transfer`), `ref_id`, `state` (`pending` | `active` | `retired`), `created_at`, `updated_at`.

**Cycle de vie d'une clé**

| Événement | Effet sur `audio_references` |
|---|---|
| Upload d'un audio (`POST /content/audio`) | Clé enregistrée en `pending`, avec son `content_id` déduit de la clé |
| `POST /content` réussi | Les clés du contenu passent en `active` |
| **Publication partielle** (upload réussi, `POST /content` en échec) | La clé reste `pending` ; elle est supprimée par la tâche de nuit au bout de 24 h si aucun `POST /content` ne l'a activée |
| Republication avec un nouvel audio | L'atelier appelle `POST /content/audio/retire` pour l'ancienne clé, qui passe en `retired` |
| Carte SRS créée depuis l'écoute active | Référence `srs_card` ajoutée sur la clé de l'extrait |
| **Carte SRS supprimée** (ou expression retirée du SRS) | Sa référence `srs_card` est supprimée dans la même transaction |
| Contenu supprimé | Ses références `content` passent en `retired` ; les références `srs_card` restent |
| Tâche de nuit | Supprime de R2 une clé `retired` depuis plus de 7 jours **seulement si** plus aucune référence `srs_card` ni `transfer` ne la vise |

**Contrôles côté Worker**
- `POST /content/audio/retire` reçoit `contentId` et `key`. Il refuse (403) si la clé n'appartient pas à ce contenu (`content_id` différent), et il refuse la clé **active** du contenu en cours.
- Seules les clés du préfixe `prepared-content/` sont concernées.
- Un ancien contenu dont des cartes SRS utilisent encore l'audio garde ce fichier, même retiré ou supprimé.

### 8.3 Séances d'écoute — lot 1

Migration `00xx_listening_sessions.sql` :

```sql
CREATE TABLE IF NOT EXISTS listening_sessions (
  id                 TEXT PRIMARY KEY NOT NULL,
  profile_id         TEXT NOT NULL,
  content_id         TEXT NOT NULL,
  content_revision   TEXT NOT NULL,
  excerpt_start_ms   INTEGER NOT NULL,
  excerpt_end_ms     INTEGER NOT NULL,
  excerpt_wpm        REAL,
  audio_origin       TEXT,                       -- original | kokoro_tts
  path_variant       TEXT NOT NULL,              -- reference | quick | decoding | supported
  first_pass_rating  TEXT NOT NULL,              -- nothing | topic | main_ideas | almost_all
  questions_total    INTEGER NOT NULL DEFAULT 0,
  questions_correct  INTEGER NOT NULL DEFAULT 0,
  marked_segments    TEXT NOT NULL DEFAULT '[]', -- JSON [{segmentId, reason, recognizedAfter}]
  retained_chunks    TEXT NOT NULL DEFAULT '[]', -- JSON [chunkId]
  is_calibration     INTEGER NOT NULL DEFAULT 0, -- 1 = extrait de contrôle (§ 11)
  started_at         TEXT NOT NULL,
  finished_at        TEXT NOT NULL,
  created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_listening_profile_time ON listening_sessions(profile_id, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_listening_profile_content ON listening_sessions(profile_id, content_id);
```

- La note de restitution **n'est pas stockée** côté serveur (elle reste locale).
- `POST /listening/sessions` : idempotent sur `id` (généré par la PWA). Ajoute un `learning_events` (`module = listen`, `event_type = active_listening_completed`).
- `GET /listening/sessions?profileId=&contentId=` : extraits déjà travaillés.
- `GET /listening/stats?profileId=` : indicateurs du § 10.

### 8.4 Expressions vers le SRS, avec un instantané autonome — lot 1

- Nouvelle route `POST /listening/promote-chunks`, sur le modèle de `/podcasts/promote-words` : 2 expressions au plus par appel, liste vide acceptée.
- L'expression est créée dans `words` :
  - `type` = `chunk` ;
  - `traduction` = `meaningFr` ;
  - `tags` = `["ecoute-active", "<contentId>"]`.
- **L'exemple contient un instantané complet**, qui ne dépend plus du contenu d'origine :

```json
{ "en": "It completely slipped my mind.", "fr": "Ça m'est complètement sorti de la tête.",
  "audio": { "key": "prepared-content/abc-1f2e3d4c.mp3", "startMs": 18240, "endMs": 20110, "origin": "original" },
  "source": { "contentId": "abc", "contentRevision": "1f2e3d4c…", "segmentId": "s004" } }
```

- La clé audio est enregistrée dans `audio_references` (§ 8.2) : elle ne peut pas disparaître tant que la carte existe.
- **Déduplication** : l'expression est normalisée (minuscules, apostrophes et espaces unifiés, ponctuation finale retirée, `something`/`someone` → `sth`/`sb`) avant la recherche dans `words`.
  - Si elle existe déjà, **aucune nouvelle carte n'est créée** : l'instantané (texte + audio) est **ajouté** aux exemples de la carte existante, sans toucher à sa progression écrite.
  - Sinon, la carte est créée comme ci-dessus.
- Le Worker indique pour chaque expression proposée si elle est déjà dans le SRS et à quel niveau, pour la phase 5.
- **Maîtrise écrite et maîtrise orale** : comprendre une expression en la lisant et la comprendre en l'entendant ne progressent pas au même rythme. Le lot 1 ne fait que **collecter** les résultats oraux (vérifications différées, `learning_events`). Le lot 2 ajoute une seconde dimension de maîtrise (table `word_listening_progress` : `profile_id`, `word_id`, niveau, prochaine révision), sans modifier `word_progress`.

### 8.5 Vérification différée — lot 1 bis

- `GET /listening/transfer-checks?profileId=` : expressions retenues il y a 3 jours ou plus (puis 10 jours ou plus), pas encore vérifiées à cette échéance, et pour lesquelles il existe un élément de transfert (§ 6.3). Chaque élément contient la phrase, son audio, la question de sens et les choix de forme.
- `POST /listening/transfer-checks` : enregistre, par test, la réponse choisie, si elle est juste, et l'auto-évaluation éventuelle. Le résultat va dans `learning_events` (`event_type = transfer_check`, `payload` détaillé).
- **Expression sans élément de transfert** :
  - à la création de la carte, le Worker l'ajoute à la file `GET /listening/transfer-queue?profileId=` (expression, contenu, `contentRevision`, date limite = J+3) ;
  - l'atelier lit cette file, prépare les tests et les publie avec le contenu ; l'expression sort alors de la file ;
  - si rien n'a été préparé à l'échéance, la vérification se fait avec le test « écouter puis choisir le sens » sur l'extrait d'origine, marquée `same_context: true` : ce test **ne compte pas** comme un transfert.

---

## 9. PWA (`englishPwa/`) — exigences

### 9.1 Nouvelle route

`/ecoute-active/:contentId` (`?extrait=n` facultatif). Page plein écran, en mode portrait, sans la barre de navigation du bas.

### 9.2 Lecture par segment

- **Pendant la lecture d'un segment ou d'une boucle**, une boucle `requestAnimationFrame` surveille `currentTime` et arrête la lecture dès que `endMs` est atteint. `timeupdate` n'est pas assez fréquent pour cela. Hors segment, `timeupdate` suffit à surligner le segment en cours.
- Marge de 120 ms avant et après chaque segment, pour ne pas couper une syllabe.
- **Tolérance visée :** ±250 ms sur Safari iOS, ±100 ms sur Chrome de bureau, mesurées pendant la recette (EA-05).
- Vitesses : 0,75×, 0,9×, 1×.
- Le lot 1 dépend des requêtes Range (§ 8.1).

### 9.3 Données lues dans le contenu

Lues dans `metadata` :
- `segments` (timings et `wordsPerMinute` par segment), `segmentationVersion`, `timingSource`, `contentRevision` ;
- `chunks`, `grammarPoints`, `connectedSpeech` (avec `verified`), `comprehensionQuestions` ;
- `transferItems` (avec la clé audio de chaque phrase), `audioOrigin`.

La lecture reste tolérante : un champ absent désactive la fonction concernée.

### 9.4 Vérification différée — lot 1 bis

Elle apparaît dans l'accueil (« 2 vérifications d'écoute ») et dure moins de 2 minutes. Pour chaque expression due, **un** des trois tests est tiré, en alternant :

| Test | Déroulé | Ce qu'il mesure |
|---|---|---|
| Sens d'une expression | Écouter la nouvelle phrase, puis répondre à « Que veut dire le locuteur ? » (4 choix) | Reconnaissance **et** compréhension |
| Compréhension en contexte | Écouter la nouvelle phrase, puis répondre à une question simple sur la situation | Compréhension dans un nouveau contexte |
| Forme sonore | Écouter la nouvelle phrase, puis retrouver l'expression entendue parmi 4 propositions écrites | Identification de la forme sonore |

- La phrase est jouée **sans texte**, une seconde écoute est permise, et le texte n'apparaît qu'après la réponse.
- Une auto-évaluation (« J'étais sûr / J'ai hésité / J'ai deviné ») est demandée **après** la réponse. Elle sert à repérer l'excès ou le manque de confiance, pas à noter.
- Les tests alimentent **deux indicateurs distincts**, jamais fusionnés en un seul score :
  - **Compréhension du sens** : tests « sens d'une expression » et « compréhension en contexte » ;
  - **Reconnaissance de la forme sonore** : test « forme sonore ». Une bonne réponse ici ne prouve pas que le sens est compris.
- Le tirage alterne de façon à ce que chaque expression passe au moins une fois un test de sens.
- Le résultat est envoyé au Worker (§ 8.5) et ajuste la carte SRS de l'expression : un échec au test de sens la rend due plus tôt.

### 9.5 Révision audio dans le SRS — lot 2

Cartes « audio d'abord » pour les expressions issues de l'écoute active : on entend l'extrait (instantané § 8.4), puis on voit l'expression, son sens et la phrase source.

### 9.6 Statistiques d'écoute — lot 2

Section « Écoute » de la page Statistiques avec les indicateurs du § 10 et l'obstacle principal (§ 7). Pas de minutes écoutées ni de nombre de séances.

### 9.7 Étiquette de difficulté — lot 3 (règles provisoires utilisables dès le lot 1)

- Chaque extrait reçoit une étiquette « Accessible », « Adapté » ou « Exigeant ». Elle se fonde sur :
  - le débit de l'extrait ;
  - le niveau du contenu ;
  - les résultats de **première écoute** (questions de sens comprises) des 5 dernières séances.
- L'étiquette est toujours accompagnée de sa raison.
- Dès le lot 1, une version minimale sert à choisir la longueur de l'extrait (§ 5.1) : un extrait n'est « accessible » que si son débit est inférieur à la médiane des extraits réussis (question juste et *Les idées principales* ou mieux).

### 9.8 Entrées dans le reste de l'app

- Fiche contenu : bouton « Écoute active », mention « Voix de synthèse » si `audioOrigin = kokoro_tts`.
- Mission du jour : peut proposer une écoute active ou des vérifications différées dues.
- Page Live : même mécanisme de copie de prompt pour la restitution.

### 9.9 Circulation des informations entre modules

L'écoute active ne doit pas devenir un module isolé. Ce qu'elle constate doit servir ailleurs :

| Constat de l'écoute active | Utilisé par | Effet |
|---|---|---|
| Expression non comprise (raison 2) puis retenue | SRS | Carte créée ou exemple audio ajouté (§ 8.4) |
| Échec au test de **sens** différé | SRS | Carte due plus tôt |
| Échecs répétés de **reconnaissance sonore** | Écoute active | Séances orientées décodage proposées en priorité (§ 5.3) |
| Expressions retenues de la semaine | Séance Live | Le prompt Live les inclut, avec la consigne de les faire réutiliser à l'oral |
| Obstacle principal (§ 7) | Mission du jour | Choix de l'activité proposée (écoute active, révisions, Live) |

Lot 1 : les deux premières lignes. Lot 1 bis : la vérification différée. Lots 2 et 3 : le reste.

---

## 10. Mesure de la progression

| Indicateur | Calcul | Statut |
|---|---|---|
| **Compréhension d'extraits inédits** | Taux de réussite aux questions de sens sur la **première écoute** d'extraits jamais entendus, en particulier les extraits de contrôle (§ 11) | **Indicateur principal** |
| **Transfert différé — sens** | Réussite aux tests « sens d'une expression » et « compréhension en contexte » (§ 9.4), séparément à J+3 et J+10 ; tests `same_context` exclus | **Indicateur principal** |
| Transfert différé — forme sonore | Réussite au test « forme sonore » à J+3 et J+10 | Indicateur secondaire, **jamais fusionné** avec le précédent |
| Compréhension déclarée à la première écoute | Répartition de l'auto-évaluation, comparée à la réussite aux questions (écart = sur- ou sous-confiance) | Indicateur secondaire |
| Reconnaissance après décodage | Part des segments marqués reconnus en phase 3 (*Reconnu* = 1, *En partie* = 0,5) | Indicateur **de séance**, pas de maîtrise |
| Activité diagnostique | Nombre de segments marqués et répartition des raisons | Indicateur **d'activité** ; sert à trouver l'obstacle principal, jamais à mesurer l'autonomie |

L'ancien indicateur « autonomie sans transcription = segments non marqués » est **supprimé**. Il dépendait de ce que l'interface demandait de marquer.

---

## 11. Protocole de 28 jours et repères de réussite

Le but est d'**observer si l'écoute active semble améliorer la compréhension d'un audio jamais entendu, et si elle mérite d'être poursuivie**. Sans groupe de comparaison, ce protocole ne peut pas attribuer avec certitude un progrès à l'écoute active : c'est un **test exploratoire** pour une application personnelle.

### 11.1 Mise en place (avant le jour 1)

**Extraits de contrôle**
- **Cible : 12 à 16 extraits.** On peut démarrer avec 8 si la préparation est trop lourde ; le protocole est alors explicitement « exploratoire réduit ».
- Audios authentiques, jamais utilisés en écoute active, marqués `is_calibration` et cachés du reste de l'app.
- **Comparables entre eux** sur quatre critères :
  - longueur (1 à 2 minutes) ;
  - débit (±10 %) ;
  - complexité lexicale (part de mots hors des 2 000 plus fréquents, ±5 points) ;
  - type de discours (monologue explicatif, dialogue, interview… : même proportion sur chaque période).
- **3 questions indépendantes par extrait**, à **4 choix**, chacune sur une idée différente. Avec 4 choix, la réussite au hasard tombe à 25 %, contre 33 % avec 3.
- **Évaluation qualitative** après chaque extrait de contrôle : « Peux-tu expliquer les idées principales sans transcription ? » L'apprenant le fait à voix haute, puis se note sur une grille fixe :
  - 0 = rien d'exploitable ;
  - 1 = le sujet ;
  - 2 = le sujet et une idée ;
  - 3 = le sujet et au moins deux idées justes.

**Contenus d'entraînement** : en majorité des audios authentiques, adaptés au niveau A2+/B1.

### 11.2 Déroulé

| Période | Entraînement | Mesure (avec 12 extraits ; 16 → 4 la première semaine et 4 la dernière) |
|---|---|---|
| Semaine 1 | Écoute active 5 jours sur 7 (parcours de référence) | **Référence** : 3 extraits de contrôle |
| Semaines 2 et 3 | Écoute active 5 jours sur 7 ; vérifications différées dès qu'elles sont dues | 3 extraits de contrôle par semaine |
| Semaine 4 | Idem | 3 derniers extraits ; bilan |

- Les extraits de contrôle se passent en début de séance, avant tout entraînement ce jour-là.
- Leur ordre est tiré au hasard dès le départ, pour ne pas mettre les plus faciles à la fin.
- On note aussi, chaque semaine, le **ressenti d'utilisation** (une phrase) et les autres activités pratiquées (Lingvist, Live…).

### 11.3 Repères de réussite

Ces seuils sont des **repères fixés à l'avance**, pas des preuves. Avec 9 à 12 questions par période, une ou deux réponses suffisent à faire varier le score de 10 points : on regarde donc **la convergence de plusieurs signaux**, pas un seul chiffre.

La méthode **semble utile et mérite d'être poursuivie** si, en comparant la semaine 1 aux semaines 3 et 4 :
1. la réussite aux questions des extraits de contrôle progresse d'environ **15 points ou plus** ;
2. **et** la note qualitative moyenne (grille 0–3) progresse d'au moins **0,5** ;
3. **et** le transfert différé **de sens** atteint environ **70 %** à J+3 et **60 %** à J+10 ;
4. **et** l'écoute active a été pratiquée au moins **16 jours sur 28**, sans abandon pour lassitude.

**Signaux mitigés** (un ou deux repères manquants) : on garde les lots 1 et 1 bis, on ajuste le parcours (longueur des extraits, adaptations du § 5.3) et on prolonge de 2 semaines avant tout développement du lot 2.

**Pas de signal** (repères 1, 2 et 3 manquants) : on ne développe pas les lots 2 et 3 ; l'écoute active reste un mode secondaire et l'effort se reporte sur l'écoute libre, le SRS et la production orale.

### 11.4 Limites assumées

- Pas de groupe de comparaison : un progrès peut venir d'autres activités menées en parallèle, ou simplement de l'habitude des questions.
- Petit nombre de questions : résultats lus comme une **tendance**.
- Auto-évaluation qualitative : subjective, d'où une grille fixe.
- Le transfert est mesuré sur des phrases en voix de synthèse (§ 6.3).

---

## 12. Contrats de données (exemples)

### 12.1 Segment horodaté (`metadata.segments[]`)

```json
{ "id": "s004", "en": "I should've told you earlier.", "fr": "J'aurais dû te le dire plus tôt.", "startMs": 18240, "endMs": 20110, "wordsPerMinute": 160 }
```

### 12.2 Enrichissements de `metadata`

```json
{
  "contentRevision": "1f2e3d4c5b6a7980",
  "segmentationVersion": 2,
  "timingSource": "macwhisper_srt",
  "audioOrigin": "original",
  "wordsPerMinute": 158,
  "connectedSpeech": [ { "written": "…", "possiblePronunciation": "…", "phenomenon": "reduction", "explanationFr": "…", "sourceSegmentId": "s004", "verified": false } ],
  "comprehensionQuestions": [ { "questionFr": "…", "choicesFr": ["…", "…", "…"], "answerIndex": 1, "segmentIds": ["s001", "s002"] } ],
  "transferItems": [ { "chunkId": "c002", "sentenceEn": "…", "audioKey": "prepared-content/abc-transfer-c002-1f2e3d4c.mp3", "voice": "bm_george", "meaningQuestionFr": "…", "meaningChoicesFr": ["…"], "meaningAnswerIndex": 0, "formChoicesEn": ["…"], "formAnswerIndex": 0 } ]
}
```

### 12.3 Séance envoyée par la PWA (`POST /listening/sessions`)

```json
{
  "id": "6f1c…",
  "profileId": "default",
  "contentId": "wtf-is-happening-with-cybersecurity",
  "contentRevision": "1f2e3d4c5b6a7980",
  "excerpt": { "startMs": 0, "endMs": 104000, "wordsPerMinute": 171 },
  "audioOrigin": "original",
  "pathVariant": "decoding",
  "firstPassRating": "main_ideas",
  "questions": { "total": 1, "correct": 1 },
  "markedSegments": [ { "segmentId": "s004", "reason": "not_recognized", "recognizedAfter": "partly" } ],
  "retainedChunks": ["c003"],
  "isCalibration": false,
  "startedAt": "2026-10-17T07:02:11Z",
  "finishedAt": "2026-10-17T07:16:40Z"
}
```

Valeurs de `reason` : `not_recognized` | `unknown_words` | `too_fast` | `meaning`.
Valeurs de `recognizedAfter` : `yes` | `partly` | `no`.
Valeurs de `pathVariant` : `reference` | `quick` | `decoding` | `supported`.

---

## 13. Critères d'acceptation

| ID | Scénario | Résultat attendu |
|---|---|---|
| EA-01 | Transcrire une vidéo anglaise | `segments.json` a des timings croissants issus du **SRT** ; `timingSource = macwhisper_srt`. |
| EA-02 | Générer l'audio Kokoro d'une vidéo française | Les timings correspondent à l'audio anglais généré (écart < 150 ms au début de chaque segment, mesuré sur 10 segments). |
| EA-03 | Modifier le texte anglais d'une source FR | Timings et audio marqués obsolètes jusqu'à la régénération. |
| EA-04 | Coller une analyse avec `verified: true` | Valeur forcée à `false` ; seule la case « Entendu dans l'audio » la fait passer à `true`. |
| EA-05 | Rejouer 20 segments sur iPhone (Safari, PWA installée) | Démarrage et arrêt à ±250 ms ; requêtes Range en 206. |
| EA-06 | Republier un contenu avec un nouvel audio | L'app lit le nouvel audio ; l'ancien reste disponible tant qu'une carte SRS le référence. |
| EA-07 | Supprimer un contenu dont une expression est dans le SRS | La carte SRS lit toujours son extrait audio. |
| EA-08 | Mener une séance complète | Séance enregistrée une seule fois, même après un nouvel essai réseau, avec la `contentRevision`. |
| EA-09 | Réussir la phase 1 (*Presque tout* + question juste) | La version courte est proposée, avec sa raison ; on peut quand même faire le parcours complet. |
| EA-10 | Échouer à la phase 1 (*Presque rien*) | Accompagnement renforcé proposé ; en fin de séance, suggestion d'un contenu plus accessible. |
| EA-11 | Phase 5 sans rien sélectionner | Séance terminée normalement, aucun ajout au SRS. |
| EA-12 | Vérification différée à J+3 (lot 1 bis) | Phrase nouvelle, autre voix, sans texte ; la réponse est notée juste ou fausse ; l'auto-évaluation est enregistrée à part. |
| EA-13 | Expression sans élément de transfert | Test sur l'extrait d'origine, marqué `same_context`, exclu de l'indicateur de transfert. |
| EA-14 | Extrait de contrôle | Jamais proposé en écoute active ; compté uniquement dans la compréhension d'extraits inédits. |
| EA-15 | Contenu sans horodatage, ou ancien contenu publié | Pas de bouton « Écoute active » ; affichage et écoute libre inchangés. |
| EA-16 | Contenu Kokoro | Mention « Voix de synthèse » ; écoute active disponible mais non mise en avant. |
| EA-17 | Retenir une expression déjà présente dans le SRS | Aucune carte en double ; l'exemple audio est ajouté à la carte existante, sa progression est inchangée. |
| EA-18 | Retenir une expression sans test de transfert | Elle apparaît dans la file « Transferts à préparer » de l'atelier, avec sa date limite. |
| EA-19 | Appeler `POST /content/audio/retire` avec la clé d'un autre contenu | Refus 403, aucune référence modifiée. |
| EA-20 | Upload audio réussi puis `POST /content` en échec | La clé reste `pending` et disparaît de R2 au bout de 24 h. |
| EA-21 | Supprimer une carte SRS d'écoute | Sa référence audio est supprimée ; le fichier part au nettoyage s'il n'est plus utilisé ailleurs. |
| EA-22 | Statistiques de transfert | « Sens » et « forme sonore » affichés séparément, jamais additionnés. |
| EA-23 | Une seule réponse fausse en phase 1, avec *Les idées principales* | Aucune adaptation proposée. |

---

## 14. Découpage en lots

### Lot 1 — Fondations

1. **Fiabiliser les audios :**
   - horodatage par SRT (EN) et par Kokoro segment par segment (FR) ;
   - `segmentationVersion` et `contentRevision` ;
   - clés audio versionnées ;
   - requêtes Range sur `/audio` ;
   - table `audio_references`, retrait et nettoyage contrôlé ;
   - contrôle de l'alignement dans l'atelier ;
   - compatibilité des anciens contenus.
2. **Construire le lecteur d'écoute active :**
   - extraits courts ;
   - lecture segmentée (`requestAnimationFrame`) ;
   - transcription masquée, boucles ;
   - diagnostic et adaptations du parcours (§ 5.3) ;
   - sauvegarde des séances.
3. **Analyse enrichie** (connected speech « possible », questions de sens) et `promote-chunks` avec instantané autonome.

À développer maintenant, **sans ajouter de fonctionnalité** au-delà de ce périmètre.

### Lot 1 bis — Vérification différée (avant le protocole)

- Prompt de transfert pour les 5 expressions prioritaires, et audios Kokoro dans l'atelier (§ 6.3).
- File « Transferts à préparer » (§ 8.5) et son affichage dans l'atelier.
- Routes de vérification différée et écran de vérification (§ 9.4), avec les **deux indicateurs séparés** (sens / forme sonore).
- Préparation des 12 à 16 extraits de contrôle (§ 11.1).
- **Puis lancement du protocole de 28 jours** : évaluations sur audios inédits, limites de l'échantillon notées, ressenti recueilli.

### Lot 2 — Consolidation du SRS (si le protocole est concluant)

- Cartes SRS « audio d'abord », introduites progressivement.
- Seconde dimension de maîtrise : **reconnaissance écrite** et **reconnaissance orale** (`word_listening_progress`, § 8.4).
- Statistiques d'écoute détaillées.
- Davantage de voix et de contextes de transfert.
- Expressions retenues reprises dans le prompt Live (§ 9.9).

### Lot 3 — Personnalisation pédagogique

- Étiquettes de difficulté complètes et suggestions dans la mission du jour (§ 9.9).
- Choix des contenus et des entraînements selon les difficultés réellement observées.

---

## 15. Risques et décisions

### 15.1 Décisions prises (anciennes questions ouvertes)

| Question | Décision |
|---|---|
| Longueur de l'extrait | 1 à 2 minutes par défaut en A2/B1 ; jusqu'à 3 minutes si l'extrait est jugé accessible. |
| Restitution | Facultative, **gardée sur le téléphone** ; synchronisation seulement si un suivi sur plusieurs appareils devient nécessaire. |
| Contenus Kokoro | Écoute active **proposée**, avec signalement clair de la voix de synthèse ; priorité aux contenus authentiques. |
| Expressions par séance | **2 par défaut**, possibilité de n'en retenir **aucune** ; seulement si elles sont utiles, nouvelles ou difficiles. |

### 15.2 Risques

| Sujet | Risque | Réponse |
|---|---|---|
| Alignement SRT ↔ segments | Une réplique coupe une phrase en deux | Regroupement sur les frontières de répliques ; contrôle à l'oreille (§ 6.6) |
| Anciens bundles | Re-segmenter oblige à refaire traduction et analyse | Action volontaire, avec avertissement |
| Kokoro segment par segment | Prosodie moins fluide aux frontières | Comparer à l'oreille sur 2 contenus avant de valider |
| Phrases de transfert en synthèse | Le transfert est mesuré face à une voix de synthèse | Limite affichée ; un lot ultérieur pourra utiliser des extraits authentiques d'autres contenus contenant la même expression |
| Auto-évaluation | Sur- ou sous-confiance | Toujours croisée avec une question de sens |
| Petit échantillon de contrôle | Résultats bruités, part de hasard | 12 à 16 extraits, 3 questions à 4 choix, grille qualitative ; lecture en tendance (§ 11.3) |
| Tests de transfert inutilisés | Travail de préparation perdu | 5 expressions prioritaires par contenu + file à la demande (§ 6.3) |
| Références audio incohérentes | Fichier supprimé encore utilisé, ou fichiers orphelins | Cycle de vie formalisé et contrôles côté Worker (§ 8.2) |
| Lassitude | Parcours répétitif | Adaptations du § 5.3 ; ressenti noté chaque semaine |

---

## 16. Consigne pour l'agent de développement

> Implémente ce cahier des charges **lot par lot** (1, puis 1 bis), en faisant évoluer l'existant :
> - atelier : `pipeline.py`, `convertisseur_web.py`, `tts_kokoro.py` ;
> - Worker : `src/content.ts`, `src/tts.ts`, nouvelles migrations ;
> - PWA : `PreparedContentCard`, `useAudioPlayer`, nouvelles pages.
>
> Vérifie chaque route et chaque nom de champ dans le code avant de l'utiliser. Écris d'abord les tests :
> - regroupement SRT → segments, timings Kokoro ;
> - validation de l'analyse enrichie (`verified` forcé à `false`) et du transfert ;
> - requêtes Range ;
> - cycle de vie des références audio (publication partielle, carte supprimée, retrait refusé pour une clé d'un autre contenu) ;
> - déduplication des expressions dans le SRS ;
> - idempotence des séances.
>
> Ne casse ni la lecture des anciens contenus ni l'écoute libre. Ne déploie le Worker et ne pousse la PWA qu'avec l'accord explicite de l'utilisateur.
