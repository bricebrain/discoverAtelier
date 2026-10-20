import io
import json
import tempfile
import threading
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest import mock

import discover_audio
import discover_deepgram as dg
import discover_speech
import discover_tts_settings as settings
from discover_tts_budget import AppelIncertain, Budget, BudgetDepasse


def wav(data=b'\0\0' * 12000):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        out.writeframes(data)
    return buffer.getvalue()


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = {'deepgramApiKey': 'fake-key', 'tts': settings.settings({'tts': {'provider': 'deepgram', 'voice': 'cora', 'speed': 1.0}})}
        self.script = [{'id': 'p0001', 'text': 'First sentence.', 'speaker': 'Narrator'},
                       {'id': 'p0002', 'text': 'Second sentence.', 'speaker': 'Guest'}]

    def tearDown(self):
        self.tmp.cleanup()

    def test_long_text_is_split_with_utf16_limit_and_without_lost_words(self):
        text = ('An important fact. ' * 400) + '😀' * 2000
        parts = dg.chunks(text)
        self.assertTrue(all(0 < dg.characters(p) <= 1800 for p in parts))
        self.assertEqual(''.join(''.join(parts).split()), ''.join(text.split()))

    def test_budget_rejects_before_http_and_retains_failed_cost(self):
        budget = Budget(self.root)
        budget.reserve('a', 100, .003)
        budget.finish('a', False)
        self.assertEqual(budget.status(.003)['engagedUsd'], .003)
        with self.assertRaises(BudgetDepasse):
            budget.reserve('b', 1, .003)
        with self.assertRaises(AppelIncertain):
            budget.reserve('a', 100, 10)

    def test_budget_is_atomic_between_threads(self):
        outcomes = []
        def reserve(key):
            try:
                Budget(self.root).reserve(key, 100, .003)
                outcomes.append('ok')
            except BudgetDepasse:
                outcomes.append('blocked')
        Budget(self.root)
        threads = [threading.Thread(target=reserve, args=(str(i),)) for i in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(outcomes, ['ok', 'blocked'])

    def test_budget_month_changes_without_forgetting_old_attempts(self):
        month = ['2026-10']
        budget = Budget(self.root, lambda: month[0])
        budget.reserve('old', 100, .003)
        month[0] = '2026-11'
        self.assertEqual(budget.status(.003)['engagedUsd'], 0)
        budget.reserve('new', 100, .003)
        with self.assertRaises(AppelIncertain): budget.reserve('old', 100, 10)

    def test_full_plan_includes_faithful_and_counts_unique_missing_fragments(self):
        config = {**self.config, 'tts': {**self.config['tts'], 'monthlyLimitUsd': .004}}
        script = [{'id': 'p', 'text': 'x' * 100}]
        faithful = [{'id': 's', 'text': 'y' * 100}]
        session = discover_speech.Session([script, faithful], self.root, config, self.root / 'prepared-test')
        self.assertEqual(session.provider, 'kokoro')
        self.assertEqual(session.estimate['estimatedUsd'], .006)
        same = discover_speech.Session([script, script], self.root, self.config, self.root / 'prepared-duplicate')
        self.assertEqual(same.estimate['newCharacters'], 100)

    def test_cache_is_shared_and_timings_match_actual_samples(self):
        transport = mock.Mock(return_value=b'\0\0' * 12000)
        for name in ['one', 'two']:
            result = dg.assemble(self.script, self.root, self.config, self.root / (name + '.wav'),
                                 self.root / (name + '.json'), lambda: None, transport)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(transport.call_args_list[0].args[1], 'aura-2-cora-en')
        self.assertEqual(transport.call_args_list[1].args[1], 'aura-2-draco-en')
        self.assertEqual(json.loads((self.root / 'two.json').read_text()), [
            {'id': 'p0001', 'startMs': 300, 'endMs': 800}, {'id': 'p0002', 'startMs': 1400, 'endMs': 1900}])
        self.assertEqual(result['durationMs'], 1900)
        with wave.open(str(self.root / 'two.wav')) as audio:
            self.assertEqual(audio.getnframes(), 45600)
            frames = audio.readframes(audio.getnframes())
            self.assertEqual(frames[:14400], b'\0' * 14400)

    def test_failure_does_not_repeat_a_potentially_billed_request(self):
        transport = mock.Mock(side_effect=dg.DeepgramIndisponible('Unavailable'))
        with self.assertRaises(dg.DeepgramIndisponible):
            dg.fragment('Hello.', self.root, self.config, lambda: None, transport)
        with self.assertRaises(AppelIncertain):
            dg.fragment('Hello.', self.root, self.config, lambda: None, transport)
        self.assertEqual(transport.call_count, 1)
        self.assertGreater(Budget(self.root).status(10)['engagedUsd'], 0)

    def test_corrupted_cache_is_not_paid_again_automatically(self):
        dg.fragment('Hello.', self.root / '.deepgram', self.config, lambda: None, lambda *args: b'\0\0' * 12000)
        path = dg.cache_path(self.root / '.deepgram', dg.fragment_key('Hello.', 'cora', 1.0))
        path.write_bytes(b'broken')
        session = discover_speech.Session([[{'text': 'Hello.'}]], self.root, self.config, self.root / 'prepared-corrupt')
        self.assertEqual(session.provider, 'kokoro')
        self.assertIn('déjà été envoyé', session.reason)

    def test_api_failure_falls_back_to_whole_kokoro_version(self):
        session = discover_speech.Session([self.script], self.root, self.config, self.root / 'prepared-error')
        with mock.patch.object(dg, 'assemble', side_effect=dg.DeepgramIndisponible('Service indisponible')), \
             mock.patch.object(discover_audio, 'calibrer', return_value={'af_heart': .95}), \
             mock.patch.object(discover_audio, 'executer', return_value={'durationMs': 1000}) as kokoro:
            result = session.generate(self.script, self.root, 'version', lambda: None)
        self.assertEqual(result['origin'], 'kokoro')
        self.assertEqual(kokoro.call_count, 1)
        self.assertEqual(session.provider, 'kokoro')

    def test_valid_wav_request_and_error_redaction(self):
        response = io.BytesIO(wav()); response.headers = {'Content-Type': 'audio/wav'}
        opener = mock.Mock(return_value=response)
        self.assertEqual(len(dg.request('Hello', 'aura-2-cora-en', 1, 'secret-value', opener)), 24000)
        self.assertIn('encoding=linear16', opener.call_args.args[0].full_url)
        with self.assertRaises(dg.DeepgramIndisponible) as raised:
            dg.request('Hello', 'aura-2-cora-en', 1, 'secret-value', mock.Mock(side_effect=urllib.error.URLError('secret-value')))
        self.assertNotIn('secret-value', str(raised.exception))

    def test_rejects_non_audio_and_redirects(self):
        response = io.BytesIO(b'{}'); response.headers = {'Content-Type': 'application/json'}
        with self.assertRaises(dg.DeepgramIndisponible):
            dg.request('Hi', 'aura-2-cora-en', 1, 'fake', lambda *a, **k: response)
        with self.assertRaises(dg.DeepgramIndisponible):
            dg.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')

    def test_cancel_before_request_costs_nothing(self):
        with self.assertRaises(RuntimeError):
            dg.fragment('Hello', self.root, self.config, mock.Mock(side_effect=RuntimeError('cancelled')))
        self.assertEqual(Budget(self.root).status(10)['engagedUsd'], 0)

    def test_default_voice_and_speed_are_relaxed(self):
        self.assertEqual(settings.settings({})['voice'], 'arcas')
        self.assertEqual(settings.settings({})['speed'], 1.0)

    def test_settings_validate_budget_and_normalize_speed(self):
        self.assertEqual(settings.settings({'tts': {'speed': 1}})['speed'], 1.0)
        for value in [-1, 101, float('nan'), True]:
            with self.assertRaises(ValueError): settings.settings({'tts': {'monthlyLimitUsd': value}})
        with self.assertRaises(ValueError): settings.settings({'tts': {'voice': 'unknown'}})


class SettingsRoutesTests(unittest.TestCase):
    def setUp(self):
        import discover_cible
        import discover_http
        self.http, self.cible = discover_http, discover_cible
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path = self.root / 'config.json'
        self.config_path.write_text(json.dumps({'workerUrl': 'https://discover.example.com', 'atelierToken': 'x' * 40,
                                               'deepgramApiKey': 'private-test-key', 'geminiModel': 'untouched'}))
        self.patches = [mock.patch.object(discover_cible, 'CONFIG', self.config_path),
                        mock.patch.object(discover_http.FILE, 'dossier', self.root), mock.patch.object(discover_http.FILE, 'config', {})]
        for patch in self.patches: patch.start()

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        self.tmp.cleanup()

    def call(self, body=None, origin='http://127.0.0.1:53782'):
        raw = json.dumps(body).encode() if body is not None else b''
        handler = mock.Mock()
        handler.path = '/api/discover/tts'
        handler.headers = {'Host': '127.0.0.1:53782', 'Origin': origin, 'X-Discover-Atelier': '1', 'Content-Length': str(len(raw))}
        handler.rfile = io.BytesIO(raw)
        self.http.traiter(handler, 'POST' if body is not None else 'GET', '/api/discover/tts')
        return handler._envoyer.call_args.args

    def test_settings_response_never_returns_keys_and_save_preserves_other_config(self):
        code, result = self.call({'provider': 'deepgram', 'voice': 'vesta', 'monthlyLimitUsd': 10})
        self.assertEqual(code, 200)
        self.assertEqual(result['settings']['voice'], 'vesta')
        self.assertNotIn('private-test-key', json.dumps(result))
        self.assertNotIn('atelierToken', json.dumps(result))
        saved = json.loads(self.config_path.read_text())
        self.assertEqual(saved['geminiModel'], 'untouched')
        self.assertEqual(saved['deepgramApiKey'], 'private-test-key')
        self.assertEqual(self.config_path.stat().st_mode & 0o777, 0o600)

    def test_foreign_origin_cannot_change_budget(self):
        before = self.config_path.read_bytes()
        self.assertEqual(self.call({'monthlyLimitUsd': 100}, 'https://evil.example')[0], 403)
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_browser_cannot_replace_api_keys(self):
        self.assertEqual(self.call({'deepgramApiKey': 'replacement'})[0], 503)
        self.assertEqual(json.loads(self.config_path.read_text())['deepgramApiKey'], 'private-test-key')
