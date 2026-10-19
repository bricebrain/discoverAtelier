"""Passage vocabulaire au repos : cadence persistante, exclusion locale et état sans secret."""
import fcntl
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import discover_vocabulary_picks
import pipeline

INTERVAL = 600
COUNTERS = ('sent', 'already_known', 'failed', 'unacknowledged')
LOG = logging.getLogger(__name__)


def _stamp(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def _read(root):
    state = pipeline.lire_json(str(Path(root) / 'vocabulary-sync.json'))
    return state if isinstance(state, dict) else {}


def _save(root, state):
    pipeline.ecrire_json(str(Path(root) / 'vocabulary-sync.json'), state)


def _running(root):
    try:
        with (Path(root) / 'vocabulary-sync.lock').open('r') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True
    except FileNotFoundError:
        return False


def status(root, config):
    state = _read(root)
    running = _running(root)
    phase = state.get('phase', 'never')
    if phase == 'running' and not running:
        phase = 'interrupted'
    return {**state, 'phase': phase, 'running': running,
            'autoEnabled': config.get('vocabularyAutoSync', True) is not False,
            'intervalSeconds': INTERVAL}


def run(root, config, request, busy=False, automatic=True, verifier=lambda: None, sync=None, now=None):
    if busy:
        return {'skipped': 'Préparation en cours'}
    if automatic and config.get('vocabularyAutoSync', True) is False:
        return {'skipped': 'Synchronisation automatique désactivée'}
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'vocabulary-sync.lock').open('a') as lock:
        (root / 'vocabulary-sync.lock').chmod(0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'skipped': 'Synchronisation déjà en cours'}
        state = _read(root)
        now = time.time() if now is None else now
        last = state.get('attemptEpoch')
        if automatic and isinstance(last, (int, float)) and now - last < INTERVAL:
            return {'skipped': 'Intervalle de dix minutes'}
        state.update(attemptEpoch=now, lastAttemptAt=_stamp(now), phase='running',
                     lastReport={key: 0 for key in COUNTERS}, mode='automatic' if automatic else 'manual')
        _save(root, state)
        try:
            def available():
                verifier()
                queue = request(config, 'GET', '/atelier/queue')['items']
                if any(item.get('status') == 'leased' for item in queue):
                    raise RuntimeError('Bail de préparation actif')

            def progress(report):
                previous = state['lastReport']
                if report['sent'] + report['already_known'] > previous['sent'] + previous['already_known']:
                    state['lastSentAt'] = _stamp(time.time())
                state['lastReport'] = dict(report)
                _save(root, state)

            # Le contrôle est aussi refait avant chaque lecture/envoi/accusé : une préparation distante garde priorité.
            available()
            report = (sync or discover_vocabulary_picks.synchroniser)(
                config, transport=request, verifier=available, on_progress=progress)
            state.update(lastReport=dict(report), lastRunAt=_stamp(time.time()),
                         phase='warning' if report['failed'] or report['unacknowledged'] else 'success')
            if state['phase'] == 'warning':
                LOG.warning('Vocabulaire Discover : certains mots attendent une reprise ; vérifier les accès et la connexion.')
            return report
        except Exception:
            state['phase'] = 'error'
            LOG.warning('Synchronisation des mots différée : vérifier la configuration, les baux et la connexion.')
            return {'error': 'Synchronisation différée. Vérifier la configuration, les baux et la connexion.'}
        finally:
            _save(root, state)
