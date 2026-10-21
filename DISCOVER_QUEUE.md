# À préparer — Discover (lots 8 et 9)

Lancer `lancer_discover.command` : la page de l’Atelier Discover s’ouvre directement. La file vient du Worker configuré dans `config_discover.json` ; le jeton n’est jamais transmis au navigateur.

Sur le téléphone, choisir **Préparer en anglais** sur un épisode. L’Atelier télécharge et normalise l’audio, récupère la transcription officielle ou utilise MacWhisper, puis prépare et publie la version choisie : Intégral, Condensé ou L’essentiel, au niveau et à la durée demandés. Le suivi et l’annulation restent disponibles dans Discover.

Gemini utilise la clé existante de `config_ia.json`, ou `geminiApiKey` dans `config_discover.json`, ou `GEMINI_API_KEY`. `geminiModel` et `geminiJudgeModel` permettent de choisir les modèles d’écriture et de contrôle séparément. L’exemple de configuration ne contient aucun secret. Kokoro utilise `venv-tts` et les modèles déjà installés sur ce Mac.

Le plan et l’extraction couvrent tous les blocs de la source. L’écriture anglaise conserve les renvois aux passages et une traduction française par paragraphe. Le second passage Gemini vérifie le fond ; les noms et nombres sont aussi contrôlés localement. Les publicités sont retirées des adaptations. La traduction fidèle facultative d’une source française conserve, elle, tout le texte original.

Une version **À relire** reste bloquée dans la file. Ouvrir **Lire et vérifier** pour comparer aux sources, corriger, régénérer ou accepter la version exacte. Une version rejetée ne peut pas être acceptée sans nouvelle correction ou génération. Les corrections repassent le contrôle. Aucun audio n’est publié sans cette validation lorsqu’elle est requise.

Kokoro produit l’audio avec des timings exacts. Son débit est calibré, puis la durée finale est vérifiée à ±20 % de la cible. Une durée encore hors cible demande une relecture supplémentaire. Les versions déjà publiées sont conservées lorsque l’on prépare une autre couverture ou un autre niveau.

Les étapes sont conservées dans `fileToImport/.discover-queue/<episode-id>/`. Les sources sont contrôlées par SHA-256, les appels Gemini sont mis en cache, les paragraphes audio Kokoro sont réutilisables. Un quota Gemini rend le bail sans pénalité et reprend dans une heure. Le plafond local de budget provoque une erreur visible, sans boucle de reprise infinie.

Un bail dure 15 minutes, renouvelé toutes les deux minutes et à chaque étape. Une perte de bail arrête les sous-processus et empêche la publication. Trois tentatives automatiques au maximum, puis **Réessayer** depuis Discover. Une seule instance locale utilise la même file de travail. Démarrer/Arrêter pilote le consommateur ; il démarre avec l’Atelier lorsque la configuration existe.

Seul **L’édito éco**, déjà configuré pour la préparation automatique, rejoint la file après collecte de son dernier épisode récent. Le Mac doit être allumé et l’Atelier lancé. Aucune demande annulée ou échouée n’est recréée automatiquement.

La copie originale reste sur demande ; le streaming officiel est le défaut. Si les timings RSS ne correspondent pas à l’audio, le texte reste lisible sans surlignage trompeur. MacWhisper Base reprend sans détection des intervenants lorsque cette option n’est pas supportée ; son modèle n’est pas changé.

Le pont d’envoi simultané vers EnglishFluency appartient au lot 12. Les travaux vocabulaire restent indépendants.

Tests : `python3 -m unittest discover -s tests -q`. Documentation détaillée : `../discover-mymind/docs/LOT9_PREPARATION.md`. Le Fold7 physique reste à vérifier, notamment écran verrouillé et plié/déplié.
