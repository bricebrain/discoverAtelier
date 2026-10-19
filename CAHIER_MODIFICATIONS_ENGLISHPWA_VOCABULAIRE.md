# Cahier de modifications — intégration du vocabulaire enrichi dans EnglishPWA

**Date :** 17 octobre 2026  
**Application cible :** `/Users/brice/mesProjects/myMobileProjects/englishPwa`  
**Backend cible :** `englishfluency-worker`  
**Source des enrichissements :** atelier Vocabulaire de `convert`

## 1. Objectif

EnglishPWA doit utiliser les corrections et enrichissements publiés depuis l’atelier Vocabulaire :

- traduction française principale corrigée ;
- lemme anglais normalisé ;
- forme d’affichage, avec `to` pour les verbes lexicaux quand c’est utile ;
- catégorie grammaticale normalisée ;
- un à trois sens avec exemples anglais/français ;
- les collocations, structures grammaticales, phrasal verbs, expressions et idiomes associés.

L’intégration ne doit ni recréer les cartes SRS ni perdre la progression existante. Le lien reste l’identifiant historique `words.id`.

## 2. Décisions fonctionnelles

### 2.1 Source de vérité

- `words` reste la source historique du mot, de son niveau, de sa fréquence, de sa phonétique et de ses fichiers audio.
- `vocabulary_enrichments` contient la version publiée et corrigée des données linguistiques.
- `word_progress` reste l’unique source de vérité pour la progression de l’utilisateur.
- EnglishPWA ne doit jamais appeler les routes `/admin/vocabulary/*`.
- Le Worker doit joindre l’enrichissement publié aux réponses métier déjà consommées par la PWA.

### 2.2 Compatibilité

L’enrichissement est facultatif dans le contrat. Tant qu’un mot n’a pas été traité par l’atelier, la PWA continue d’utiliser les champs historiques :

1. `enrichment.primaryTranslation`, sinon `traduction` ;
2. `enrichment.displayForm`, sinon `mot` pour l’affichage ;
3. `enrichment.lemma`, sinon `mot` pour la réponse attendue, la recherche et l’identification lexicale ;
4. premier sens enrichi, sinon `exemple_en` et `exemple_fr` ;
5. `enrichment.partOfSpeech`, sinon `type`.

Le déploiement peut donc être progressif : les 50 mots déjà publiés bénéficient immédiatement de la nouvelle présentation, les autres restent inchangés.

### 2.3 Règle du `to`

- `lemma` ne contient jamais `to`.
- `displayForm` peut contenir `to` pour un verbe lexical à l’infinitif.
- Un modal (`can`, `must`, `should`, etc.) ne contient jamais `to`.
- Une réponse à saisir dans Lingvist ou une phrase à trou utilise `expectedAnswer` ou `lemma`, jamais `displayForm`.
- La synthèse vocale prononce le lemme ou la phrase complète, pas automatiquement `displayForm`.

Exemple :

```text
lemma       = "range"
displayForm = "to range"

Affichage du mot dans une fiche : "to range"
Réponse attendue dans « Prices ____ from 10 to 20 » : "range"
```

### 2.4 Données internes à ne pas afficher

Les champs suivants servent à l’atelier ou à l’audit et ne sont pas nécessaires dans l’interface d’apprentissage :

- `originalWord` ;
- `originalTranslation` ;
- `originalType` ;
- `reviewRequired` ;
- `reviewNote` ;
- `source_snapshot` ;
- `batchId`.

Ils restent stockés côté Worker pour la traçabilité et le retour arrière.

## 3. Contrat attendu du Worker

### 3.1 Objet exposé à la PWA

Les mots renvoyés par les routes d’apprentissage reçoivent une propriété facultative `enrichment` :

```ts
/** Catégorie grammaticale libre, validée comme chaîne non vide côté Worker. */
export type VocabularyPartOfSpeech = string;

export type VocabularyCollocationKind =
  | 'collocation'
  | 'grammar_pattern'
  | 'phrasal_verb'
  | 'idiom'
  | 'expression';

export interface VocabularySenseDto {
  senseKey: string;
  partOfSpeech: VocabularyPartOfSpeech;
  translation: string;
  exampleEn: string;
  exampleFr: string;
}

export interface VocabularyCollocationDto {
  en: string;
  fr: string;
  kind: VocabularyCollocationKind;
  senseKey: string;
}

export interface VocabularyEnrichmentDto {
  schemaVersion: 1;
  version: number;
  publishedAt: string;
  lemma: string;
  displayForm: string;
  partOfSpeech: VocabularyPartOfSpeech;
  primaryTranslation: string;
  translationStatus:
    | 'correct'
    | 'incomplete'
    | 'incorrect_as_standalone'
    | 'incorrect'
    | 'ambiguous';
  senses: VocabularySenseDto[];
  collocations: VocabularyCollocationDto[];
}
```

Exemple de mot renvoyé :

```json
{
  "id": "range_1879",
  "mot": "range",
  "traduction": "intervalle",
  "niveau": "B1",
  "type": "word",
  "enrichment": {
    "schemaVersion": 1,
    "version": 1,
    "publishedAt": "2026-10-16T22:55:51.942Z",
    "lemma": "range",
    "displayForm": "to range",
    "partOfSpeech": "verb",
    "primaryTranslation": "aller de… à…",
    "translationStatus": "incorrect",
    "senses": [
      {
        "senseKey": "vary-between-limits",
        "partOfSpeech": "verb",
        "translation": "aller de… à…",
        "exampleEn": "Prices range from 10 to 20 euros.",
        "exampleFr": "Les prix vont de 10 à 20 euros."
      }
    ],
    "collocations": [
      {
        "en": "range from … to …",
        "fr": "aller de… à…",
        "kind": "grammar_pattern",
        "senseKey": "vary-between-limits"
      }
    ]
  }
}
```

### 3.2 Routes à enrichir

Le Worker doit inclure cet objet dans :

- `GET /srs/session` : nécessaire aux flashcards ;
- `GET /lingvist/session` dans chaque élément de `words` : nécessaire au contexte Lingvist et aux variantes ;
- `GET /srs/triage` : version allégée ou objet complet, nécessaire au tri des mots ;
- `GET /srs/progress` : route historique/debug, pour conserver un contrat homogène ;
- les routes `/words` et `/words/:id` si elles sont encore utilisées par un écran futur.

Il ne faut pas créer un appel PWA par mot. Le `LEFT JOIN` doit être fait côté Worker afin d’éviter un problème N+1.

### 3.3 Cartes Lingvist déjà mises en cache

Les lignes `lingvist_cards` existantes peuvent contenir l’ancienne traduction dans `word_traduction_fr`. Deux protections sont nécessaires côté Worker :

- lors de la réponse `/lingvist/session`, remplacer `wordTraductionFr` par `enrichment.primaryTranslation` lorsque la carte cible bien le même mot ;
- à terme, associer la version d’enrichissement à la carte ou invalider/reconstruire la carte quand `enrichment.version` change.

La première règle permet une correction immédiate sans supprimer toutes les cartes préparées.

## 4. Modifications dans EnglishPWA

### 4.1 Types

Créer `src/types/vocabulary.ts` pour les types ci-dessus, puis étendre les modèles existants dans `src/types/learning.ts` :

```ts
export interface SrsWord {
  // champs existants inchangés
  enrichment?: VocabularyEnrichmentDto | null;
}

export interface SrsTriageCandidate {
  // champs existants inchangés
  enrichment?: VocabularyEnrichmentDto | null;
}
```

Le champ reste facultatif et nullable pour accepter les anciens Worker, les mocks et les mots non encore enrichis.

### 4.2 Helpers métier

Créer `src/helpers/vocabularyDisplay.ts` avec des fonctions pures :

```ts
getVocabularyLemma(word)
getVocabularyDisplayForm(word)
getVocabularyTranslation(word)
getVocabularyPartOfSpeech(word)
getVocabularyExamples(word)
getVocabularyAcceptedAnswers(word, direction)
```

Ces fonctions concentrent tous les fallbacks. Les pages et hooks ne doivent plus choisir directement entre `mot`, `traduction` et `enrichment`.

Règles particulières :

- `getVocabularyAcceptedAnswers` retourne plusieurs réponses acceptables sans confondre tous les sens ;
- côté français, `primaryTranslation` est prioritaire et les traductions des sens peuvent être acceptées comme variantes ;
- côté anglais, le lemme est toujours accepté ; `displayForm` est accepté uniquement après retrait contrôlé du préfixe `to ` ;
- les valeurs vides ou génériques ne sont jamais présentées.

### 4.3 Mapping API

Modifier `src/api/learningApi.ts` pour :

- typer les réponses enrichies ;
- conserver l’objet `enrichment` lors du mapping de `/lingvist/session` ;
- remplacer le fallback `word?.traduction` par `getVocabularyTranslation(word)` ;
- ne pas appeler `/admin/vocabulary/enrichments` ;
- ne pas modifier les payloads de `/srs/review`, car le Worker doit continuer à identifier la progression avec `wordId`.

Pour éviter d’alourdir `learningApi.ts`, le mapping d’un DTO peut être placé dans `src/api/mappers/vocabularyMapper.ts` seulement si une transformation réelle est nécessaire.

### 4.4 Flashcards

Modifier `src/hooks/useFlashcardSession.ts` :

- forme anglaise affichée : `getVocabularyDisplayForm` ;
- réponse anglaise attendue : `getVocabularyLemma` ;
- traduction : `getVocabularyTranslation` ;
- évaluation : accepter une liste de réponses et non une seule chaîne concaténée ;
- conserver `currentWord.id` pour toute sauvegarde SRS.

Modifier `src/helpers/flashcardEvaluation.ts` pour ajouter une API explicite :

```ts
evaluateRecall(answer: string, acceptedAnswers: string[]): RecallResult
```

La compatibilité avec l’ancienne signature peut être gardée temporairement si d’autres appels existent.

Modifier `src/pages/FlashcardsPage.tsx` :

- prononcer le lemme, pas la chaîne `to + verbe` ;
- afficher l’exemple du premier sens sur le verso ;
- ajouter, après révélation seulement, une zone compacte « Autres sens et expressions » ;
- ne pas montrer les autres sens avant la réponse, afin de ne pas donner la solution.

Créer un composant présentatif `src/components/vocabulary/WordEnrichmentDetails.tsx` pour les sens et collocations. Il doit utiliser Material UI v5 et reprendre le style des cartes existantes.

### 4.5 Lingvist

Modifier `src/api/learningApi.ts` :

- `wordTraductionFr` utilise d’abord la traduction fournie par la carte, puis la traduction enrichie du mot, puis la traduction historique ;
- `srsWord` conserve l’enrichissement.

Modifier `src/hooks/useLingvistSession.ts` :

- les variantes peuvent utiliser les exemples des sens enrichis en complément de `srsWord.examples` ;
- `expectedAnswer` reste la forme exigée par la phrase ;
- `lemma` sert à retrouver le mot, sans ajouter `to`.

`src/pages/LingvistPage.tsx` et `src/components/lingvist/LingvistResultPanel.tsx` peuvent afficher, après validation :

- la traduction principale corrigée ;
- le sens lié à la phrase si le Worker transmet un `senseKey` ;
- au maximum deux collocations pertinentes pour ne pas surcharger l’exercice.

Le prompt de `src/api/lingvistAnalysisApi.ts` bénéficiera automatiquement de la traduction corrigée via `wordTraductionFr`.

### 4.6 Tri des mots faciles

Étendre la réponse de `/srs/triage`, puis modifier :

- `src/types/learning.ts` ;
- `src/api/learningApi.ts` ;
- `src/pages/TriagePage.tsx`.

La carte affiche `displayForm`, la traduction corrigée et la catégorie normalisée. Le bouton audio prononce le lemme.

Le geste « Je connais » continue uniquement de mettre à jour `word_progress`. Il ne supprime pas le mot du Worker et ne modifie pas son enrichissement.

### 4.7 React Query et rafraîchissement

Les clés actuelles restent valides :

- `['srs-session', profileId]` ;
- `['lingvist-session', profileId]` ;
- `['srs-triage', profileId]`.

Un enrichissement publié sera chargé au prochain refetch ou rechargement de la PWA. Aucun stockage local durable du dictionnaire n’est actuellement nécessaire.

Pour rendre la mise à jour visible rapidement pendant la phase de correction :

- garder `staleTime` court pour le SRS ;
- conserver au maximum cinq minutes pour Lingvist ;
- proposer un refetch manuel dans les écrans qui en possèdent déjà un ;
- ne pas vider globalement le cache à chaque ouverture.

## 5. Découpage recommandé par fichiers

### Nouveaux fichiers PWA

- `src/types/vocabulary.ts` — contrat des enrichissements ;
- `src/helpers/vocabularyDisplay.ts` — sélecteurs et fallbacks purs ;
- `src/helpers/vocabularyDisplay.test.ts` — règles du lemme, du `to`, des traductions et des exemples ;
- `src/components/vocabulary/WordEnrichmentDetails.tsx` — affichage présentatif après révélation.

### Fichiers PWA à modifier

- `src/types/learning.ts` ;
- `src/api/learningApi.ts` ;
- `src/api/learningApi.contract.test.ts` ;
- `src/helpers/flashcardEvaluation.ts` et son test ;
- `src/hooks/useFlashcardSession.ts` ;
- `src/pages/FlashcardsPage.tsx` ;
- `src/hooks/useLingvistSession.ts` ;
- `src/pages/LingvistPage.tsx` ;
- `src/components/lingvist/LingvistResultPanel.tsx` ;
- `src/pages/TriagePage.tsx` ;
- `src/mocks/srsData.ts` et `src/mocks/learningData.ts`.

### Fichiers Worker à modifier avant l’intégration PWA

- `src/srs.ts` — joindre l’enrichissement aux sessions et au tri ;
- `src/lingvistSession.ts` — joindre l’enrichissement et corriger le fallback des cartes préparées ;
- `src/vocabulary.ts` — exposer l’enrichissement sur les routes de lecture si nécessaire ;
- un helper partagé, par exemple `src/vocabularyEnrichmentMapper.ts`, pour parser et sérialiser `data` une seule fois ;
- les tests de contrat correspondants.

## 6. Tests obligatoires

### Helpers PWA

- un mot sans enrichissement garde exactement l’ancien comportement ;
- `to range` est affiché, mais la réponse attendue reste `range` ;
- `can` ne devient jamais `to can` ;
- la traduction enrichie remplace la traduction historique ;
- plusieurs traductions valides peuvent être acceptées ;
- un sens ou une collocation mal formé ne fait pas planter l’écran.

### Contrat API PWA

- `/srs/session` conserve `enrichment` ;
- `/lingvist/session` utilise la traduction enrichie comme fallback ;
- `/srs/triage` conserve `enrichment` ;
- un payload sans `enrichment` reste accepté ;
- `/srs/review` envoie toujours le même `wordId`.

### Parcours fonctionnels

- flashcard EN→FR avec traduction corrigée ;
- flashcard FR→EN d’un verbe affiché avec `to`, réponse sans `to` acceptée ;
- modal sans `to` ;
- Lingvist utilisant une ancienne carte préparée mais la nouvelle traduction ;
- affichage des sens/collocations uniquement après la réponse ;
- tri « Je connais » sans perte de progression ;
- retour au fallback historique sur un mot non enrichi.

### Vérifications finales

```bash
npm test
npm run lint
npm run build
```

## 7. Ordre d’implémentation conseillé

1. Ajouter le mapper partagé et les `LEFT JOIN` dans le Worker.
2. Tester les contrats `/srs/session`, `/lingvist/session` et `/srs/triage`.
3. Ajouter les types et helpers PWA avec leurs tests.
4. Brancher les flashcards.
5. Brancher Lingvist et gérer les anciennes cartes préparées.
6. Brancher le tri des mots.
7. Ajouter le panneau compact des sens et collocations.
8. Exécuter tests, lint et build, puis tester un mot enrichi et un mot non enrichi en production.

## 8. Critères d’acceptation

La modification est terminée lorsque :

- une correction publiée dans l’atelier apparaît dans EnglishPWA sans modifier `words` ;
- les mots non encore enrichis continuent de fonctionner ;
- aucune progression SRS n’est perdue ou réinitialisée ;
- les verbes utilisent `to` seulement pour l’affichage approprié ;
- Lingvist exige toujours la forme grammaticale imposée par la phrase ;
- les sens et collocations sont lisibles sans alourdir la face avant des exercices ;
- l’application ne fait aucun appel aux routes d’administration ;
- les tests, le lint et le build de la PWA passent.

## 9. Hors périmètre de cette intégration

- modifier automatiquement les 4 000 mots depuis la PWA ;
- exposer l’historique des versions ou le rollback à l’utilisateur final ;
- supprimer un mot du corpus `words` depuis un écran d’apprentissage ;
- appeler un modèle IA pendant chaque session ;
- dupliquer les enrichissements dans le stockage local du navigateur.

L’IA est utilisée dans l’atelier pour produire et valider les enrichissements. La consultation dans EnglishPWA doit rester déterministe, rapide et sans coût IA supplémentaire.
