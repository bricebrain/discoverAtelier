"""Les lectures locales ne provoquent une lecture D1 que sur changement ou en secours."""
import json
import threading
import unittest
from unittest.mock import Mock, patch

from discover_live import LiveQueue
from discover_queue import FileDiscover


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.wake = threading.Event()
        self.live = LiveQueue(self.wake, lambda: self.now)
        self.request = Mock(return_value={'items': []})

    def test_repeated_ui_reads_share_one_remote_read(self):
        for _ in range(900):
            self.live.read({}, self.request)
        self.request.assert_called_once_with({}, 'GET', '/atelier/queue')

    def test_change_and_reconnection_invalidate_cache_and_wake_engine(self):
        self.live.read({}, self.request)
        for kind in ('queue.changed', 'work.changed', 'connected'):
            self.wake.clear()
            self.live.message(json.dumps({'type': kind}))
            self.assertTrue(self.wake.is_set())
            self.live.read({}, self.request)
        self.assertEqual(self.request.call_count, 4)
        self.assertTrue(self.live.connected)

    def test_ping_pong_does_not_reread_queue(self):
        self.live.read({}, self.request)
        self.live.message('pong')
        self.live.read({}, self.request)
        self.assertFalse(self.wake.is_set())
        self.assertEqual(self.request.call_count, 1)

    def test_fallback_refreshes_after_five_minutes(self):
        self.live.read({}, self.request)
        self.now = 299
        self.live.read({}, self.request)
        self.assertEqual(self.request.call_count, 1)
        self.now = 300
        self.live.read({}, self.request)
        self.assertEqual(self.request.call_count, 2)

    def test_event_during_fetch_is_not_lost(self):
        def fetch(*args):
            self.live.invalidate()
            return {'items': []}
        self.request.side_effect = fetch
        self.live.read({}, self.request)
        self.request.side_effect = None
        self.live.read({}, self.request)
        self.assertEqual(self.request.call_count, 2)

    def test_bearer_stays_in_handshake_and_redirects_are_disabled(self):
        stopped = threading.Event()
        connection = Mock()
        def recv():
            stopped.set()
            return '{"type":"connected"}'
        connection.recv.side_effect = recv
        with patch('websocket.create_connection', return_value=connection) as connect:
            self.live._listen({'workerUrl': 'https://discover.example', 'atelierToken': 'private'}, stopped)
        self.assertEqual(connect.call_args.args, ('wss://discover.example/atelier/events',))
        self.assertEqual(connect.call_args.kwargs['redirect_limit'], 0)
        self.assertEqual(connect.call_args.kwargs['header'], {'Authorization': 'Bearer private'})
        connection.close.assert_called_once()

    def test_event_wakes_idle_engine_without_remote_polling(self):
        worker = FileDiscover(requete=Mock(), source_only=True)
        worker.wake.set()
        self.assertFalse(worker._attendre())
        worker.requete.assert_not_called()
        worker.arreter()
        self.assertTrue(worker._attendre())


if __name__ == '__main__':
    unittest.main()
