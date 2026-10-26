# Original guidé : compréhension sur toute la transcription

Les nouvelles préparations guidées conservent l'anglais intégral et produisent
des annotations françaises consultables dans le texte. Les vidéos anglaises
gardent leur audio original. Les textes anglais sont lus tels quels ; les sources
françaises gardent la traduction anglaise naturelle et la voix existantes.

## Génération

- `discover_annotations.py` examine tous les segments par blocs d'environ
  350 mots avec le segment voisin avant et après pour contexte.
- Chaque segment doit être présent exactement une fois dans la réponse du bloc,
  même s'il ne contient aucune difficulté retenue.
- Le niveau A2 cible A2/A2+ : sens inhabituels, expressions, verbes à particule
  et constructions gênant la compréhension. Les explications sont en français.
- Zéro à trois annotations par segment : plafond, sans nombre minimal imposé.
- Aucune recherche externe ni affirmation sur une prononciation non écoutée.
- La traduction française complète reste disponible à la demande.
- La sélection d'un extrait de 2 à 5 minutes concerne uniquement les exercices
  de dictée, quiz et réécoute. Elle ne limite plus les aides de compréhension.

Le client IA existant garde ses fournisseurs, sa validation, son cache et ses
réessais. Le plafond de préparation suit la longueur pour couvrir traduction et
annotations. Les réponses sont réutilisées si le texte et les consignes restent
identiques. Les dépenses réelles restent celles du registre de coûts existant.

## Contrat et affichage

Le contrat `discover-mymind/contracts/segments.schema.json` ajoute le champ
facultatif `guide.annotations`. Sa présence, y compris un tableau vide, identifie
un guide intégralement analysé. Les anciens guides restent acceptés.

Chaque annotation contient `segmentId`, `text`, `meaning`, `note`, `startChar`
et `endChar`. Les positions comptent les **points de code Unicode**, fin exclue.
L'Atelier calcule les positions depuis la citation exacte et son occurrence,
puis l'Atelier et le Worker vérifient les citations, bornes, chevauchements et
densité. La PWA conserve le texte original et ignore un surlignage incohérent.

Dans la PWA, toucher une expression ouvre son sens et son explication, avec
accès à la lecture depuis la phrase et à l'ajout à la révision. Le panneau
présente l'écoute complète en premier et les exercices sur extrait comme
facultatifs. Les nouveaux composants utilisent Material UI v5.

## Mise en service

Les changements concernent les deux dépôts. Déployer d'abord le Worker et la
PWA de `discover-mymind` avec le contrat et son validateur généré, puis relancer
l'Atelier mis à jour. L'ancien serveur refuserait le nouveau champ d'annotations.
Cette modification du code ne déploie rien et ne relance aucune préparation payante.

Les contenus déjà publiés gardent leur ancien guide ; ils doivent être préparés
de nouveau pour recevoir les annotations. Les nouvelles demandes manuelles
proposent A2 par défaut. Les niveaux déjà enregistrés pour les préparations
automatiques sont respectés : vérifier les réglages par chaîne si nécessaire.

## Vérification

Depuis l'Atelier, une fois le contrat voisin mis à jour :

```sh
python3 -m unittest discover -s tests -q
git diff --check
```

Depuis `discover-mymind` : tests PWA et Worker, vérifications TypeScript,
génération des validateurs et construction de la PWA. Les tests de génération
utilisent des réponses simulées ; la qualité pédagogique réelle reste à vérifier
sur des vidéos représentatives après mise en service.
