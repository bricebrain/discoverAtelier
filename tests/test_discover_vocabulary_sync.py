"""Synchronisation au repos : horloge, transports et file simulés ; aucun envoi réel."""
import fcntl
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import discover_queue
import discover_vocabulary_picks as picks
import discover_vocabulary_sync as sync
import discover_http
from test_discover_http import Gestionnaire, poster

REPORT = {'sent': 2, 'already_known': 1, 'failed': 0, 'unacknowledged': 0}


class SyncSchedulingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.request = Mock(return_value={'items': []})
        def send(config, transport, verifier, on_progress):
            verifier()
            on_progress(REPORT)
            return dict(REPORT)
        self.send = Mock(side_effect=send)

    def run_sync(self, now=10000, **kwargs):
        return sync.run(self.root, kwargs.pop('config', {}), self.request, sync=self.send, now=now, **kwargs)

    def test_default_interval_survives_reloads_and_manual_bypasses(self):
        self.assertEqual(self.run_sync(), REPORT)
        self.assertIn('skipped', self.run_sync(now=10599))
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.run_sync(now=10600), REPORT)
        self.assertEqual(self.run_sync(now=10601, automatic=False), REPORT)
        self.assertIn('skipped', self.run_sync(now=11200))
        self.assertEqual(self.send.call_count, 3)
        state = sync.status(self.root, {})
        self.assertEqual(state['phase'], 'success')
        self.assertEqual(state['lastReport'], REPORT)
        self.assertIsNotNone(state['lastSentAt'])
        self.assertIsNotNone(state['lastRunAt'])
        self.assertEqual(state['intervalSeconds'], 600)
        self.assertFalse(state['running'])

    def test_disabled_and_busy_never_call_remote_or_create_state(self):
        self.assertIn('skipped', self.run_sync(config={'vocabularyAutoSync': False}))
        self.assertIn('skipped', self.run_sync(busy=True))
        self.request.assert_not_called()
        self.send.assert_not_called()
        self.assertFalse((self.root / 'vocabulary-sync.json').exists())
        self.assertFalse(sync.status(self.root, {'vocabularyAutoSync': False})['autoEnabled'])
        self.assertEqual(self.run_sync(config={'vocabularyAutoSync': False}, automatic=False), REPORT)

    def test_active_remote_lease_defers_and_errors_are_throttled(self):
        self.request.return_value = {'items': [{'status': 'leased'}]}
        with self.assertLogs(sync.LOG, level='WARNING'):
            self.assertIn('error', self.run_sync())
        self.send.assert_not_called()
        self.request.reset_mock()
        self.assertIn('skipped', self.run_sync(now=10015))
        self.request.assert_not_called()
        self.request.return_value = {'items': []}
        self.assertEqual(self.run_sync(now=10600), REPORT)

    def test_failure_keeps_partial_report_without_secrets(self):
        def fail(*args, **kwargs):
            kwargs['on_progress'](REPORT)
            raise RuntimeError('TOKEN-super-secret body-user-word')
        self.send.side_effect = fail
        with self.assertLogs(sync.LOG, level='WARNING') as logs:
            result = self.run_sync(config={'atelierToken': 'TOKEN-super-secret'})
        state = sync.status(self.root, {})
        self.assertEqual(state['phase'], 'error')
        self.assertEqual(state['lastReport'], REPORT)
        self.assertIsNotNone(state['lastSentAt'])
        self.assertNotIn('TOKEN-super-secret', json.dumps([result, state, logs.output]))
        self.assertNotIn('body-user-word', json.dumps([result, state, logs.output]))
        self.assertIn('skipped', self.run_sync(now=10015))

    def test_warning_for_failed_or_unacknowledged_selections(self):
        def incomplete(*args, **kwargs):
            report = {**REPORT, 'failed': 1, 'unacknowledged': 2}
            kwargs['on_progress'](report)
            return report
        self.send.side_effect = incomplete
        with self.assertLogs(sync.LOG, level='WARNING'):
            self.run_sync()
        self.assertEqual(sync.status(self.root, {})['phase'], 'warning')

    def test_empty_pass_does_not_claim_a_send(self):
        self.send.side_effect = lambda *a, **k: {key: 0 for key in sync.COUNTERS}
        self.run_sync()
        self.assertNotIn('lastSentAt', sync.status(self.root, {}))

    def test_file_lock_excludes_threads_and_status_detects_running(self):
        entered, release = threading.Event(), threading.Event()
        def hold(*args, **kwargs):
            entered.set()
            release.wait(3)
            return dict(REPORT)
        self.send.side_effect = hold
        thread = threading.Thread(target=self.run_sync)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertTrue(sync.status(self.root, {})['running'])
            self.assertIn('skipped', self.run_sync(automatic=False))
            self.assertEqual(self.send.call_count, 1)
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(sync.status(self.root, {})['running'])

    def test_stale_running_after_crash_is_reported_as_interrupted(self):
        (self.root / 'vocabulary-sync.json').write_text('{"phase":"running"}')
        self.assertEqual(sync.status(self.root, {})['phase'], 'interrupted')

    def test_lock_from_another_open_descriptor_is_honoured(self):
        with (self.root / 'vocabulary-sync.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn('skipped', self.run_sync())
            self.send.assert_not_called()

    def test_cancelled_before_network_never_sends(self):
        with self.assertLogs(sync.LOG, level='WARNING'):
            self.run_sync(verifier=Mock(side_effect=discover_queue.BailPerdu()))
        self.request.assert_not_called()
        self.send.assert_not_called()


class SyncTransferTests(unittest.TestCase):
    def test_checks_before_send_and_ack_and_reports_missing_ack_on_stop(self):
        row = {'id': 'pick', 'status': 'pending', 'word': 'word', 'sentence': 'A word.',
               'contentId': 'c', 'publicationId': 'p', 'variantKey': 'en', 'segmentIndex': 0, 'language': 'en'}
        request = Mock(return_value={'picks': [row], 'nextAfter': None})
        ef = Mock(return_value={'ok': True, 'status': 'sent', 'wordId': 'word'})
        check = Mock(side_effect=[None, None, discover_queue.BailPerdu()])
        progress = Mock()
        with self.assertRaises(discover_queue.BailPerdu):
            picks.synchroniser({}, request, ef, {'profileId': 'default'}, verifier=check, on_progress=progress)
        ef.assert_called_once()
        self.assertEqual(request.call_count, 1)
        self.assertEqual(progress.call_args.args[0]['unacknowledged'], 1)

    def test_new_remote_preparation_interrupts_between_operations(self):
        with tempfile.TemporaryDirectory() as root:
            request = Mock(side_effect=[{'items': []}, {'items': [{'status': 'leased'}]}])
            def transfer(*args, **kwargs):
                kwargs['verifier']()
                self.fail('Le bail aurait dû interrompre la synchronisation.')
            with self.assertLogs(sync.LOG, level='WARNING'):
                self.assertIn('error', sync.run(root, {}, request, sync=transfer))
            self.assertEqual(request.call_count, 2)


class QueueIntegrationTests(unittest.TestCase):
    def test_idle_only_and_failure_does_not_stop_polling(self):
        for source_only in (False, True):
            with self.subTest(source_only=source_only), tempfile.TemporaryDirectory() as root:
                worker = discover_queue.FileDiscover(root, requete=Mock(return_value={'item': None}), source_only=source_only)
                worker.config = {}
                worker.stop.wait = Mock(side_effect=[False, True])
                with patch('discover_queue.discover_articles.traiter_en_attente'), \
                        patch('discover_queue.discover_related.run'), \
                        patch('discover_queue.discover_vocabulary_sync.run', side_effect=OSError('cache')) as run:
                    with patch('logging.Logger.warning'):
                        worker._executer()
                self.assertEqual(worker.requete.call_count, 2)
                self.assertEqual(run.call_count, 0 if source_only else 2)

    def test_preparation_path_never_runs_idle_sync(self):
        with tempfile.TemporaryDirectory() as root:
            worker = discover_queue.FileDiscover(root, requete=Mock(return_value={'item': {'id': 'job'}}))
            worker.config = {}
            worker._traiter = Mock(side_effect=lambda: worker.stop.set())
            with patch('discover_queue.discover_vocabulary_sync.run') as run:
                worker._executer()
            worker._traiter.assert_called_once()
            run.assert_not_called()


class HttpStatusTests(unittest.TestCase):
    def test_status_is_local_and_does_not_trigger_sync(self):
        handler = Gestionnaire('/api/discover/vocabulary/status')
        with patch.object(discover_http.FILE, 'config', {'vocabularyAutoSync': False}), \
                patch('discover_http.discover_vocabulary_sync.status', return_value={'phase': 'never'}) as status, \
                patch('discover_http.discover_vocabulary_sync.run') as run:
            discover_http.traiter(handler, 'GET', handler.path)
        self.assertEqual(handler.reponses, [(200, {'phase': 'never'})])
        status.assert_called_once()
        run.assert_not_called()

    def test_manual_route_uses_same_scheduler_and_respects_csrf(self):
        path = '/api/discover/vocabulary/sync'
        with patch.object(discover_http.FILE, 'config', {'test': True}), \
                patch.object(discover_http.FILE, 'item', None), \
                patch('discover_http.discover_vocabulary_sync.run', return_value=REPORT) as run:
            handler = poster(path, {})
            discover_http.traiter(handler, 'POST', path)
            self.assertEqual(handler.reponses, [(200, REPORT)])
            self.assertFalse(run.call_args.kwargs['automatic'])
            discover_http.traiter(Gestionnaire(path), 'POST', path)
            run.assert_called_once()


class CliTests(unittest.TestCase):
    def test_cli_preserves_nonzero_failure_and_uses_shared_lock(self):
        for result in (REPORT, {'error': 'Synchronisation différée.'}):
            with self.subTest(result=result), patch('sys.argv', ['discover_vocabulary_picks.py']), \
                    patch('discover_cible.charger_config', return_value={}), \
                    patch('discover_vocabulary_sync.run', return_value=result) as run, patch('builtins.print'):
                if 'error' in result:
                    with self.assertRaises(SystemExit) as error:
                        picks.main()
                    self.assertEqual(error.exception.code, 1)
                else:
                    picks.main()
                self.assertFalse(run.call_args.kwargs['automatic'])
