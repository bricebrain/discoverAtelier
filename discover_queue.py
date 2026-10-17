"""Consommateur de la file Discover, indépendant des jobs YouTube et du vocabulaire."""
import fcntl
import re
import threading
import uuid
from pathlib import Path

import bundles
import discover_cible
import discover_source
import pipeline


class BailPerdu(RuntimeError):
    pass


class FileDiscover:
    def __init__(self, dossier=None, requete=None, preparer=None):
        self.dossier = Path(dossier or Path(bundles.DOSSIER_BUNDLES) / '.discover-queue')
        self.requete = requete or discover_cible.requete
        self.preparer = preparer or discover_source.preparer
        self.verrou = threading.RLock()
        self.stop = threading.Event()
        self.perdu = threading.Event()
        self.thread = None
        self.item = None
        self.config = None
        self.etape = 'download'
        self.message = ''
        self.owner = None
        self.lockfile = None

    def _sauver(self):
        self.dossier.mkdir(parents=True, exist_ok=True)
        path = self.dossier / 'state.json'
        pipeline.ecrire_json(str(path), {'owner': self.owner, 'item': self.item, 'stage': self.etape})
        path.chmod(0o600)

    def _appel(self, action, data):
        try:
            return self.requete(self.config, 'POST', '/atelier/queue' + action, data)
        except discover_cible.ErreurDiscover as erreur:
            if erreur.code == 'lease_lost':
                self.perdu.set()
                raise BailPerdu('Ce bail appartient désormais à une autre instance.') from None
            raise

    def verifier(self):
        if self.perdu.is_set() or self.stop.is_set():
            raise BailPerdu('Travail arrêté : bail perdu ou arrêt demandé.')

    def _heartbeat(self):
        self.verifier()
        try:
            return self._appel('/' + self.item['id'] + '/heartbeat',
                               {'leaseToken': self.item['leaseToken'], 'stage': self.etape})
        except Exception:
            # Une coupure réseau rend l'autorité incertaine : arrêter avant toute écriture distante.
            self.perdu.set()
            raise BailPerdu('Bail non confirmé : la préparation a été arrêtée.') from None

    def _signaux(self, termine):
        while not termine.wait(120):
            try:
                self._heartbeat()
            except BailPerdu:
                return

    def demarrer(self):
        with self.verrou:
            if self.thread and self.thread.is_alive():
                return
            self.config = discover_cible.charger_config()
            self.dossier.mkdir(parents=True, exist_ok=True)
            lockfile = (self.dossier / 'instance.lock').open('a')
            try:
                fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lockfile.close()
                raise ValueError('Un Atelier traite déjà cette file sur ce Mac.') from None
            self.lockfile = lockfile
            etat = pipeline.lire_json(str(self.dossier / 'state.json')) or {}
            self.owner = etat.get('owner') or str(uuid.uuid4())
            self.item = etat.get('item')
            self.etape = etat.get('stage', 'download')
            self.stop.clear()
            self.perdu.clear()
            self.thread = threading.Thread(target=self._executer, daemon=True)
            self.thread.start()

    def arreter(self):
        self.stop.set()

    def etat(self):
        with self.verrou:
            return {'running': bool(self.thread and self.thread.is_alive()), 'stage': self.etape,
                    'item': ({k: v for k, v in self.item.items() if k not in ('leaseToken', 'source')}
                             if self.item else None), 'message': self.message}

    def liste(self):
        config = self.config or discover_cible.charger_config()
        return self.requete(config, 'GET', '/atelier/queue')

    def _etape(self, etape):
        self.etape = etape
        self._heartbeat()
        self._sauver()

    def _traiter(self):
        termine = threading.Event()
        thread = threading.Thread(target=self._signaux, args=(termine,), daemon=True)
        thread.start()
        try:
            # Les chemins ne viennent jamais du titre ni du nom de fichier de l'éditeur.
            uuid.UUID(self.item['id'])
            dossier = self.dossier / self.item['ref']
            if not re.fullmatch(r'[0-9a-f]{20}', self.item['ref']):
                raise ValueError('Identifiant source invalide.')
            resultat = self.preparer(self.item, dossier, self._etape, self.verifier)
            self._etape('source_ready')
            # Aucun heartbeat ne doit arriver après la restitution du bail.
            termine.set()
            thread.join()
            self.verifier()
            self._appel('/' + self.item['id'] + '/release',
                        {'leaseToken': self.item['leaseToken'], 'sourceReady': True})
            self.message = 'Source importée et transcrite. En attente de la génération de la version adaptée.'
            if isinstance(resultat, dict) and resultat.get('speakersDetected') is False:
                self.message += ' Le modèle MacWhisper installé ne détecte pas les intervenants.'
        finally:
            termine.set()
            thread.join()

    def _executer(self):
        try:
            # Le bail local n'est repris qu'après confirmation du Worker, même après une veille.
            if self.item:
                try:
                    self._heartbeat()
                except BailPerdu:
                    self.item = None
                    self.perdu.clear()
                    self._sauver()
            while not self.stop.is_set():
                if self.item is None:
                    self.item = self._appel('/lease', {'owner': self.owner, 'sourceOnly': True})['item']
                    self.etape = 'download'
                    self._sauver()
                if not self.item:
                    if not self.message:
                        self.message = 'À jour. En attente des demandes envoyées depuis Discover.'
                    if self.stop.wait(15):
                        break
                    continue
                try:
                    self._traiter()
                except BailPerdu:
                    self.message = 'Préparation interrompue. Le Worker attribuera un nouveau bail.'
                    if self.stop.is_set() and not self.perdu.is_set():
                        self._appel('/' + self.item['id'] + '/release', {'leaseToken': self.item['leaseToken']})
                    break
                except Exception as erreur:
                    # Aucune URL signée, contenu ni sortie de commande dans les erreurs distantes.
                    self._appel('/' + self.item['id'] + '/fail',
                                {'leaseToken': self.item['leaseToken'], 'error': 'Import ou transcription impossible. Vérifier ffmpeg, MacWhisper et le flux dans l’Atelier.', 'retryable': True})
                    self.message = 'Import interrompu : ' + str(erreur)[:300]
                    if self.stop.wait(5):
                        break
                self.item = None
                self._sauver()
        except Exception:
            self.message = 'Connexion Discover impossible. Vérifier la configuration et relancer.'
        finally:
            self._sauver()
            if self.lockfile:
                self.lockfile.close()
                self.lockfile = None


FILE = FileDiscover()
