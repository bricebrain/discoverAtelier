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


VIDEO = 'dQw4w9WgXcQ'
ITEM = {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'ref': VIDEO, 'kind': 'youtube',
        'leaseToken': 'private-lease-token', 'options': {'coverage': 'full'},
        'source': {'kind': 'youtube', 'videoId': VIDEO, 'url': 'https://www.youtube.com/watch?v=' + VIDEO,
                   'title': 'Video', 'language': 'en'}}
VTT = 'WEBVTT\n\n00:01.000 --> 00:03.000\nA short <b>story</b>.\n'
VTT_AUTO = ('WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n \nA<00:00:01.500><c> short</c><00:00:02.000><c> story.</c>\n\n'
            '00:00:03.000 --> 00:00:03.010\nA short story.\n \n')


class FausseVideo:
    """yt_dlp.YoutubeDL simulé : métadonnées, pistes de sous-titres et audio téléchargé."""
    appels = []

    def __init__(self, options=None, pistes=None):
        self.options = options or {}
        self.pistes = pistes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        return {'title': 'Video', 'language': 'en', **(self.pistes or {})}

    def download(self, urls):
        FausseVideo.appels.append(urls)
        Path(self.options['outtmpl'].replace('%(ext)s', 'mp3')).write_bytes(b'audio')


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

    def preparer(self, folder, pistes, sous_titres=None, commande=None):
        """Prépare la source de la vidéo simulée ; renvoie (résultat, appels à ffmpeg/MacWhisper)."""
        FausseVideo.appels = []
        def normaliser(args, verify):
            Path(args[-1]).write_bytes(b'normalized-audio')
        def telecharger(url, base, cle, automatique):
            if sous_titres is None:
                return None
            chemin = Path(base + '.' + cle + '.vtt')
            chemin.write_text(sous_titres)
            return str(chemin)
        with mock.patch('yt_dlp.YoutubeDL', side_effect=lambda options=None: FausseVideo(options, pistes)), \
                mock.patch('transcription.telecharger_sous_titres', side_effect=telecharger), \
                mock.patch.object(source, 'commande', side_effect=commande or normaliser) as appels, \
                mock.patch.object(source, 'ffmpeg', return_value='ffmpeg'):
            return source.preparer_youtube(ITEM, folder, lambda _: None, lambda: None), appels

    def test_youtube_automatic_subtitles_resume_by_hash_and_rebuild_corrupt_audio(self):
        pistes = {'subtitles': {}, 'automatic_captions': {'en-orig': [], 'fr': []}}
        with tempfile.TemporaryDirectory() as folder:
            result, ffmpeg = self.preparer(folder, pistes, VTT_AUTO)
            self.assertEqual(result['timingSource'], 'rss_vtt')
            segments = json.loads(Path(result['segmentsFile']).read_text())['segments']
            self.assertEqual([(s['text'], s['startMs'], s['endMs']) for s in segments], [('A short story.', 1000, 3000)])
            self.assertEqual((len(FausseVideo.appels), ffmpeg.call_count), (1, 1))
            _, ffmpeg = self.preparer(folder, pistes, VTT_AUTO)
            self.assertEqual((len(FausseVideo.appels), ffmpeg.call_count), (0, 0))
            (Path(folder) / 'source.mp3').write_bytes(b'corrupted')
            _, ffmpeg = self.preparer(folder, pistes, VTT_AUTO)
            self.assertEqual((len(FausseVideo.appels), ffmpeg.call_count), (0, 1))

    def test_macwhisper_only_without_subtitles_and_without_speaker_detection(self):
        def execute(args, verify):
            if args[0] == 'ffmpeg':
                Path(args[-1]).write_bytes(b'normalized')
            elif '--speakers' in args:
                raise source.IntervenantsIndisponibles()
            else:
                self.assertIn('--no-speakers', args)
                Path(args[args.index('--output') + 1]).write_text(VTT)
        with tempfile.TemporaryDirectory() as folder, mock.patch('transcription.trouver_macwhisper', return_value='mw'):
            result, _ = self.preparer(folder, {'subtitles': {}, 'automatic_captions': {}}, commande=execute)
            self.assertEqual(result['timingSource'], 'macwhisper_srt')
            self.assertTrue(Path(result['segmentsFile']).is_file())

    def test_podcast_episodes_are_refused(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(RuntimeError):
            source.preparer_source({'ref': 'a' * 20, 'source': {'kind': 'episode'}}, folder, lambda _: None, lambda: None)

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
