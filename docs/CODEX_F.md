# Brief F — Pont EnglishFluency

Livraison du 19 octobre 2026, branche `codex/f-englishfluency`, worktree
`/Users/brice/mesProjects/myMobileProjects/convert-codex-f`, base `feat/lot1` (`60dd864`).
Périmètre limité à F. Aucun déploiement, appel payant, transfert réel ou changement de branche de `convert/`.

## Fichiers

- `discover_englishfluency.py` : mapping pur, transport HTTP injectable, paquet local, état atomique, verrou et commande de reprise.
- `discover_preparation.py` : import et appel isolé après publication Discover et comptabilité locale ; résultat Discover conservé.
- `config_discover.example.json` : bloc `englishFluency`, désactivé par défaut.
- `tests/test_discover_englishfluency.py` : contrat, préparation simulée, erreurs partielles, idempotence, reprise et transport factice.
- `docs/CODEX_F.md` : contrat, exploitation et limites de cette livraison.

Aucun fichier modifié dans Discover, ses PWA/Worker, les trois dépôts EnglishFluency, ou le checkout principal de convert.
Les fichiers personnels non commités ont uniquement été lus lorsque demandés. Pas de dépendance ajoutée.

## Contrat réellement vérifié

Sources locales consultées :

- `englishfluency-worker/src/content.ts`, `audioReferences.ts`, `utils.ts`, routage `index.ts` ;
- `englishfluency-app/src/services/preparedContentService.ts`, `types/preparedContent.ts`,
  `helpers/preparedContentLanguage.ts`, `components/listening/PreparedContentSection.tsx` ;
- `englishPwa/src/api/learningApi.ts`, `helpers/preparedContent.ts` et tests de contrat correspondants ;
- publication existante de l'Atelier : `bundles.py`, `convertisseur_web.py` (lecture seule),
  `pipeline.py` (`payload_distant`, `publier`) ; chaîne Discover et contrats JSON partagés.

| Discover, adaptation anglaise courante | EnglishFluency |
| --- | --- |
| Identité contenu + clé variante + profil | `id = discover-` + 40 hex SHA-256 du triplet ; stable entre révisions |
| Variante courante seulement | `type: podcast`, `profileId`, titre, niveau, catégorie dans `topic` |
| `segments[].text` | `body`, `metadata.textEn`, `transcriptText`, `segments[].en` |
| `segments[].fr` de cette adaptation | `metadata.textFr`, `segments[].fr` ; jamais le français original à sa place |
| Langue d'apprentissage | `metadata.language: en`, `learningLanguage: en`, `transcriptLanguage: en` |
| Origine | `sourceLanguage`, `sourceType`, `sourceUrl`, `discoverContentId`, `discoverVariantKey` |
| MP3 anglais déjà généré | upload brut `POST /content/audio?key=...&contentId=...` |
| SHA-256 complet des octets audio | clé immuable `prepared-content/<id>-<sha256>.mp3`, `audioRevision` |
| Timings Kokoro/Deepgram présents dans le document publié | `segments[].startMs/endMs`, `timingStatus: valid`, `listeningAvailable` |
| Audio sans timings exploitables / texte seul | timings `null`, écoute synchronisée désactivée ; texte conservé |
| Origine Kokoro / Deepgram | `audioOrigin: kokoro_tts` / `deepgram` |
| `keyVocab: string[]` | `metadata.keyVocab`, dédupliqué ; `chunks: []`, `grammarPoints: []` |

Les fichiers locaux texte/audio sont vérifiés contre les SHA-256 du manifeste publié. Aucun chemin local dans le payload distant.
L'audio doit être non vide et au plus 100 Mio, limite du Worker. Aucun téléchargement d'audio original ni nouvelle génération.

Le Worker exige `Authorization: Bearer <apiSecret>` pour les deux POST. L'upload inscrit une référence `pending`, puis
`POST /content` active la clé et effectue un upsert D1 sur `id`. Une réponse JSON `ok: true` est exigée aux deux étapes ;
l'accusé audio doit aussi confirmer la clé. Transport sans suivi de redirection, taille de réponse bornée et audio envoyé en flux.

**Vocabulaire :** Discover fournit des mots anglais, pas des définitions françaises. Le Worker conserve `metadata.keyVocab`,
mais la PWA affiche les éléments de `metadata.chunks`, qui exigent `expression` ET `meaningFr`.
Aucune définition n'est inventée ni aucun mot inséré dans les cartes SRS. Le vocabulaire clé est transmis et conservé ;
son affichage comme liste brute demanderait une évolution du client EnglishFluency (hors périmètre, aucun changement effectué).
Le badge Deepgram n'est pas reconnu par le helper de voix actuel de cette PWA ; audio et texte restent lisibles.

## Option et fonctionnement

Dans le `config_discover.json` local, configurer le bloc de l'exemple :

```json
"englishFluency": {
  "enabled": false,
  "workerUrl": "https://englishfluency.<compte>.workers.dev",
  "apiSecret": "",
  "profileId": "default"
}
```

L'option Atelier « aussi vers EnglishFluency » correspond à `englishFluency.enabled` : activation explicite dans ce fichier,
appliquée aux préparations suivantes. Utiliser les valeurs EnglishFluency de `config_import.json` si souhaité,
sans copier le jeton Discover ni exposer les secrets au navigateur. `__global__` est aussi accepté par les deux clients.
Il n'y a pas de nouvel interrupteur HTML ni de changement des réglages persistants existants.

Ordre : publication Discover confirmée → écriture `published.json` → comptabilité existante → pont facultatif.
Toute exception du pont, y compris configuration ou disque, est isolée : la préparation retourne toujours le succès Discover.
Aucun état d'échec n'est envoyé à la file Discover après son commit. Le pont ne réutilise pas le bail clôturé.

Fichiers de fonctionnement dans chaque dossier `prepared-*` :

- `englishfluency-packet.json` : payload figé, chemin local du MP3 et destination URL/profil, sans secret ;
- `englishfluency-state.json` : empreinte de destination/payload, identifiant distant, état
  `pending`, `audio_uploaded`, `published` ou `failed`, message d'erreur générique ;
- `englishfluency.lock` : verrou de fichier interprocessus, doublé d'un verrou de threads.

Une seconde exécution avec le même payload déjà `published` ne fait aucun appel EnglishFluency.
Si l'upload ou le POST échoue, si la réponse au POST se perd après commit, ou si le checkpoint disparaît,
le retry utilise le même ID et la même clé : aucun contenu ni objet audio supplémentaire.
Le MP3 est renvoyé à chaque reprise inachevée : les références `pending` peuvent être nettoyées après 24 h.
Une correction remplace le contenu du même ID ; une autre variante ou un autre profil reçoit un autre ID.
Les secrets et les messages arbitraires du transport ne sont jamais persistés dans les états ou affichés par le pont.

## Reprise locale

Après vérification de la configuration, depuis le checkout intégré de l'Atelier :

```sh
python3 discover_englishfluency.py /chemin/vers/prepared-xxxxxxxxxxxxxxxx --config /chemin/vers/config_discover.json
```

Cette commande **effectue un envoi réel si l'option est activée** : documentée, mais jamais exécutée contre un service réel
pendant ce chantier. Elle exige `published.json` en état `ready`, le paquet local et le MP3 intact.
Elle n'appelle ni Discover, ni Gemini/OpenAI, ni TTS. Une destination URL/profil différente de celle du paquet est refusée ;
une rotation du secret sur la même destination reste possible. Code de sortie 0 pour `published`, 1 sinon.
La préparation n'est pas relancée depuis la file Discover déjà close. Pas de relance automatique en boucle.

## Vérifications

- Tests ciblés : `python3 -m unittest discover -s tests -p test_discover_englishfluency.py -q`.
- Suite requise : `python3 -m unittest discover -s tests -q`.
- `git diff --check`.

Premier passage complet dans le bac à sable : 196 tests, cinq erreurs d'environnement
(quatre ouvertures de serveur localhost interdites, une configuration locale absente attendue par un ancien test).
Un `config_discover.json` **ignoré et non commité**, purement factice, a été créé uniquement dans ce worktree :
`workerUrl: http://127.0.0.1:1`, jeton factice de plus de 32 caractères, pont désactivé.
Aucun secret de l'Atelier principal n'a été copié. Relance avec permission d'ouvrir les serveurs localhost :
**196 tests OK**, dont les dix premiers tests du pont. Un ResourceWarning non bloquant apparaît dans la suite existante.
Les nouveaux tests interdisent les connexions sortantes et injectent tous les clients/moteurs/transports ; le test HTTP
remplace aussi la connexion elle-même. Les tests d'intégration fabriquent un vrai manifeste Discover à partir d'une préparation
factice, vérifient le paquet v2 puis reprennent l'échec EnglishFluency sans republier Discover.
Les résultats finaux après ajout des tests de garde et de commande locale sont consignés ci-dessous.

## Limites et intégration Opus

- Seulement l'adaptation anglaise courante : pas de republication des anciennes variantes conservées dans le manifeste,
  de la traduction fidèle, ni de l'original. Pas de rétropublication automatique des préparations faites avant activation.
- Le retry exige le paquet enregistré et les fichiers locaux conservés. Une panne de configuration/mapping/disque
  avant création du paquet est signalée dans le Terminal ; la commande seule ne reconstruit pas ce paquet absent.
- L'option est globale et pilotée par configuration. Une sélection par préparation dans l'interface nécessiterait
  une évolution coordonnée des routes/options ; elle n'est pas simulée en modifiant le contrat de la file Discover.
- Le Worker ne fournit pas de condition de révision pour `/content` : ne pas relancer manuellement un ancien paquet
  après publication d'une correction plus récente du même contenu/variante/profil depuis un autre dossier/Mac.
  Le verrou protège un dossier local, pas plusieurs Macs ni plusieurs dossiers.
- Une réussite mémorisée ne vérifie pas ensuite une suppression/éviction distante. EnglishFluency conserve au plus
  50 contenus par type et profil, puis évince le plus ancien lors d'une nouvelle création : comportement existant conservé.
- Aucun test de production ni recette téléphone ; Opus relit, fusionne et relance l'Atelier.

**Changements proposés pour `bundles.py` / `convertisseur_web.py` : aucun nécessaire pour cette livraison.**
Le point d'entrée existant appelle déjà `discover_preparation.preparer` via la file.
Un futur interrupteur visuel et un bouton de reprise pourraient être ajoutés dans les modules Discover locaux
(`discover_http.py`, `discover_queue.html/js`), en chantier séparé. Aucun fichier vocabulaire touché.

Résultats finaux : **199 tests OK en 3,911 s**, dont **13 tests du pont** ; `git diff --check` sans erreur.
Commande complète exécutée dans le worktree : `python3 -m unittest discover -s tests -q`.
Les cinq fichiers énumérés sont livrés ensemble dans un commit ciblé en français, suffixé `Co-Authored-By: Codex`.
