"""Événements Discover : connexion partagée du Mac et cache de la file distante."""
import json
import logging
import random
import threading
import time
from urllib.parse import urlsplit, urlunsplit


class LiveQueue:
    def __init__(self, wake, clock=time.monotonic):
        self.wake = wake
        self.clock = clock
        self.lock = threading.RLock()
        self.fetch_lock = threading.Lock()
        self.start_lock = threading.Lock()
        self.version = 0
        self.cached_version = -1
        self.cached_at = 0
        self.cached = None
        self.connected = False
        self.thread = None
        self.stopped = threading.Event()
        self.socket = None
        self.target = None

    def invalidate(self):
        with self.lock:
            self.version += 1
        self.wake.set()

    def message(self, raw):
        if raw == 'pong':
            return
        event = json.loads(raw)
        if event.get('type') == 'connected':
            with self.lock:
                self.connected = True
            self.invalidate()
        elif event.get('type') in ('queue.changed', 'work.changed'):
            self.invalidate()

    def read(self, config, request):
        # Une seule lecture distante même si plusieurs onglets locaux interrogent la file.
        with self.fetch_lock:
            with self.lock:
                version = self.version
                if self.cached is not None and self.cached_version == version and self.clock() - self.cached_at < 300:
                    return self.cached
            result = request(config, 'GET', '/atelier/queue')
            with self.lock:
                self.cached, self.cached_at, self.cached_version = result, self.clock(), version
            return result

    def start(self, config):
        with self.start_lock:
            self._start(config)

    def _start(self, config):
        target = (config.get('workerUrl'), config.get('atelierToken'))
        with self.lock:
            if self.thread and self.thread.is_alive() and self.target == target:
                return
        self.close()
        with self.lock:
            self.target = target
            self.cached = None
            self.stopped = threading.Event()
            self.thread = threading.Thread(target=self._listen, args=(dict(config), self.stopped), daemon=True)
            self.thread.start()

    def close(self):
        self.stopped.set()
        if self.socket:
            self.socket.close()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    def _listen(self, config, stopped):
        try:
            import websocket
        except ImportError:
            logging.getLogger(__name__).warning('Installer les dépendances de l’Atelier pour activer les événements Discover.')
            return
        url = urlsplit(config['workerUrl'])
        endpoint = urlunsplit(('wss' if url.scheme == 'https' else 'ws', url.netloc, '/atelier/events', '', ''))
        attempt = 0
        while not stopped.is_set():
            connection = None
            try:
                # Aucun suivi de redirection : le Bearer reste exclusivement sur le Worker configuré.
                connection = websocket.create_connection(endpoint, timeout=35, redirect_limit=0,
                    header={'Authorization': 'Bearer ' + config['atelierToken']}, suppress_origin=True)
                with self.lock:
                    if not stopped.is_set():
                        self.socket = connection
                waiting_pong = False
                while not stopped.is_set():
                    try:
                        raw = connection.recv()
                    except websocket.WebSocketTimeoutException:
                        if waiting_pong:
                            raise ConnectionError('Connexion interrompue') from None
                        connection.send('ping')
                        waiting_pong = True
                        continue
                    if not raw:
                        break
                    if len(raw) > 4096:
                        raise ValueError('Événement trop volumineux')
                    self.message(raw)
                    if raw == 'pong':
                        waiting_pong = False
                    elif json.loads(raw).get('type') == 'connected':
                        attempt = 0
            except Exception:
                # Les exceptions réseau peuvent contenir des en-têtes ; ne jamais les journaliser.
                pass
            finally:
                with self.lock:
                    if self.stopped is stopped:
                        self.connected = False
                if connection:
                    connection.close()
                with self.lock:
                    if self.socket is connection:
                        self.socket = None
            if stopped.wait(min(60, 2 ** min(attempt, 6)) + random.random()):
                break
            attempt += 1
