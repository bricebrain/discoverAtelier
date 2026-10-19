"""File Discover : bail, reprise, cache source et téléchargements sûrs, sans réseau distant."""
import io
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover_cible
import discover_download as download
import discover_queue
import discover_source as source


ITEM = {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'ref': 'a' * 20,
        'leaseToken': 'private-lease-token', 'options': {'coverage': 'full'},
        'source': {'audioUrl': 'https://cdn.example.com/audio.mp3', 'language': 'en',
                   'transcriptUrl': 'https://cdn.example.com/episode.vtt', 'transcriptType': 'vtt'}}
VTT = 'WEBVTT\n\n00:01.000 --> 00:03.000\nA short <b>story</b>.\n'


class DownloadTests(unittest.TestCase):
    def test_private_dns_credentials_and_ports_are_rejected(self):
        for url in ['file:///etc/passwd', 'https://user:pass@example.com/a',
                    'https://example.com:8080/a', 'http://127.0.0.1/a']:
            with self.subTest(url=url), mock.patch.object(socket, 'getaddrinfo', return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))]):
                with self.assertRaises(ValueError):
                    download.cible_publique(url)

    def test_mixed_public_private_dns_is_rejected(self):
        with mock.patch.object(socket, 'getaddrinfo', return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', 443))]):
            with self.assertRaises(ValueError):
                download.cible_publique('https://example.com/a')

    def test_oversize_stream_leaves_no_partial_file(self):
        response = mock.Mock(status=200)
        response.getheader.return_value = None
        response.read.side_effect = [b'abcd', b'efgh', b'']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'download.audio'
            with mock.patch.object(download, 'ouvrir', return_value=(mock.Mock(), response)):
                with self.assertRaises(ValueError):
                    download.telecharger('https://example.com/a', path, 5)
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix('.audio.part').exists())

    def test_redirect_is_revalidated(self):
        response = mock.Mock(status=302)
        response.getheader.return_value = 'http://127.0.0.1/private'
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(download, 'ouvrir', side_effect=[
                (mock.Mock(), response), ValueError('Adresse privée')]) as opener:
            with self.assertRaises(ValueError):
                download.telecharger('https://example.com/a', Path(folder) / 'a', 100)
            self.assertEqual(opener.call_args_list[1].args[0], 'http://127.0.0.1/private')


class SourceTests(unittest.TestCase):
    def test_vtt_timing_and_markup(self):
        self.assertEqual(source.repliques(VTT), [{'startMs': 1000, 'endMs': 3000, 'text': 'A short story.'}])

    def test_resumes_by_hash_and_rebuilds_corrupt_audio(self):
        def transfer(url, path, limit, verify):
            Path(path).write_bytes(VTT.encode() if url.endswith('.vtt') else b'audio')
            return download.empreinte(path)
        def normalize(args, verify):
            Path(args[-1]).write_bytes(b'normalized-audio')
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(source, 'telecharger', side_effect=transfer) as fetch, \
                mock.patch.object(source, 'commande', side_effect=normalize) as ffmpeg, mock.patch.object(source, 'ffmpeg', return_value='ffmpeg'):
            result = source.preparer(ITEM, folder, lambda _: None, lambda: None)
            self.assertEqual(result['timingSource'], 'rss_vtt')
            self.assertEqual(fetch.call_count, 2)
            source.preparer(ITEM, folder, lambda _: None, lambda: None)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(ffmpeg.call_count, 1)
            (Path(folder) / 'source.mp3').write_bytes(b'corrupted')
            source.preparer(ITEM, folder, lambda _: None, lambda: None)
            self.assertEqual(ffmpeg.call_count, 2)
            self.assertEqual(fetch.call_count, 2)

    def test_macwhisper_base_falls_back_without_speaker_detection(self):
        episode = dict(ITEM, source={**ITEM['source'], 'transcriptUrl': None})
        def transfer(url, path, limit, verify):
            Path(path).write_bytes(b'audio')
            return download.empreinte(path)
        def execute(args, verify):
            if args[0] == 'ffmpeg':
                Path(args[-1]).write_bytes(b'normalized')
            elif '--speakers' in args:
                raise source.IntervenantsIndisponibles()
            else:
                self.assertIn('--no-speakers', args)
                Path(args[args.index('--output') + 1]).write_text(VTT)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(source, 'telecharger', side_effect=transfer), \
                mock.patch.object(source, 'commande', side_effect=execute), mock.patch.object(source, 'ffmpeg', return_value='ffmpeg'), \
                mock.patch('transcription.trouver_macwhisper', return_value='mw'):
            result = source.preparer(episode, folder, lambda _: None, lambda: None)
            self.assertEqual(result['timingSource'], 'macwhisper_srt')
            self.assertFalse(result['speakersDetected'])
            self.assertTrue(Path(result['segmentsFile']).is_file())

    def test_lost_lease_stops_subprocess(self):
        process = mock.Mock()
        process.poll.return_value = None
        process.__enter__ = mock.Mock(return_value=process)
        process.__exit__ = mock.Mock(return_value=False)
        with mock.patch.object(source.subprocess, 'Popen', return_value=process):
            with self.assertRaises(discover_queue.BailPerdu):
                source.commande(['ffmpeg'], mock.Mock(side_effect=discover_queue.BailPerdu()))
        process.terminate.assert_called_once()


class QueueTests(unittest.TestCase):
    def test_restart_revalidates_before_reusing_intermediates(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = discover_queue.FileDiscover(folder, requete=mock.Mock(), preparer=mock.Mock())
            worker.owner, worker.item = 'mac', dict(ITEM)
            worker._sauver()
            def request(config, method, path, data=None):
                if path.endswith('/heartbeat'):
                    raise RuntimeError('Discover 409 : lease_lost')
                worker.stop.set()
                return {'item': None}
            worker.requete = mock.Mock(side_effect=request)
            worker._executer()
            worker.preparer.assert_not_called()
            self.assertEqual(worker.requete.call_args_list[0].args[2], '/atelier/queue/' + ITEM['id'] + '/heartbeat')
            self.assertIsNone(worker.item)

    def test_source_checkpoint_releases_without_claiming_done(self):
        with tempfile.TemporaryDirectory() as folder:
            request = mock.Mock(return_value={})
            worker = discover_queue.FileDiscover(folder, requete=request, preparer=mock.Mock(), source_only=True)
            worker.item, worker.config = dict(ITEM), {}
            worker._traiter()
            last = request.call_args_list[-1]
            self.assertTrue(last.args[2].endswith('/release'))
            self.assertEqual(last.args[3], {'leaseToken': ITEM['leaseToken'], 'sourceReady': True})
            self.assertNotIn(ITEM['leaseToken'], json.dumps(worker.etat()))

    def test_publication_carries_lease_for_upload_and_commit(self):
        from manifeste_validation import contrats
        manifest = json.loads((contrats() / 'fixtures/valid-youtube.json').read_text())
        path = next(iter(manifest['files']))
        with mock.patch.object(discover_cible, 'requete', side_effect=[
                {'publicationId': 'id', 'status': 'uploading', 'missing': [path]},
                {}, {'status': 'ready'}]) as request:
            discover_cible.publier_manifeste(manifest, {path: '/tmp/audio'}, config={'workerUrl': 'https://discover.example.com'}, demande=ITEM)
        self.assertEqual(request.call_args_list[0].args[3]['leaseToken'], ITEM['leaseToken'])
        for call in request.call_args_list[1:]:
            self.assertEqual(call.kwargs['headers']['X-Discover-Lease-Token'], ITEM['leaseToken'])
