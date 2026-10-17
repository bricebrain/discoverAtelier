# À préparer — Discover (lot 8)

Lancer `lancer_atelier.command`, puis **À préparer · Discover** dans la barre de l’Atelier. La file est lue depuis le Worker configuré dans `config_discover.json`, jamais depuis le navigateur avec le jeton.

- La préparation démarre automatiquement au lancement de l’Atelier si la configuration Discover existe. Les boutons Démarrer et Arrêter permettent de la piloter.
- Sur le téléphone : détail d’un épisode → **Préparer en anglais**. Suivi et annulation sur l’épisode ou dans Bibliothèque.
- Le lot 8 importe l’audio, le normalise (mono, 24 kHz, 64 kbit/s) et récupère le SRT/VTT officiel, ou transcrit localement avec MacWhisper.
- La détection des intervenants est demandée à MacWhisper. Si le modèle ne la supporte pas (Base sur ce Mac), un second passage sans détection est utilisé et signalé. Aucun changement du modèle configuré dans MacWhisper.
- Les fichiers sont conservés dans `fileToImport/.discover-queue/<episode-id>/`, avec contrôle SHA-256 avant réutilisation. Ils sont réutilisables après un arrêt ou une veille.
- Un bail dure 15 minutes, renouvelé toutes les deux minutes et à chaque étape. Une perte de bail arrête le sous-processus ; aucune publication n’est alors effectuée. Trois tentatives automatiques au maximum, puis Réessayer depuis Discover.
- Le lot 8 laisse les demandes au stade **Source prête · adaptation à venir**, sans les annoncer comme terminées. Le lot 9 générera et évaluera les adaptations avant publication. Le bail source est rendu, ce qui permet d’importer les autres demandes.
- Une seule instance locale peut utiliser la même file de travail à la fois.

La publication des bundles YouTube existants reste accessible depuis Contenus. Le vocabulaire et ses travaux en cours restent indépendants.

Tests : `python3 -m unittest discover -s tests -p 'test_discover*.py' -v`.
