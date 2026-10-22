"""La perte du bail interrompt le travail, sans arrêter le consommateur."""
import tempfile
import unittest
from unittest import mock

from discover_queue import BailPerdu, FileDiscover


class RepriseTests(unittest.TestCase):
    def test_bail_perdu_redemande_un_bail_avant_de_reprendre(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = FileDiscover(folder)
            worker.owner = 'mac'
            premier = {'id': 'premier', 'leaseToken': 'ancien'}
            second = {'id': 'second', 'leaseToken': 'nouveau'}
            worker._appel = mock.Mock(side_effect=[{'item': premier}, {'item': second}])

            def traiter():
                if worker.item is premier:
                    worker.perdu.set()
                    raise BailPerdu()
                worker.verifier()
                worker.stop.set()

            worker._traiter = mock.Mock(side_effect=traiter)
            with mock.patch.object(worker.stop, 'wait', return_value=False) as attente:
                worker._executer()

            self.assertEqual(worker._traiter.call_count, 2)
            self.assertEqual(worker._appel.call_args_list, [
                mock.call('/lease', {'owner': 'mac', 'sourceOnly': False}),
                mock.call('/lease', {'owner': 'mac', 'sourceOnly': False}),
            ])
            attente.assert_called_once_with(30)
            self.assertFalse(worker.perdu.is_set())

    def test_arret_demande_libere_le_bail_sans_reprendre(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = FileDiscover(folder)
            worker.owner = 'mac'
            item = {'id': 'premier', 'leaseToken': 'ancien'}
            worker._appel = mock.Mock(return_value={'item': item})

            def traiter():
                worker.stop.set()
                worker.verifier()

            worker._traiter = mock.Mock(side_effect=traiter)
            worker._executer()
            worker._traiter.assert_called_once()
            worker._appel.assert_called_with('/premier/release', {'leaseToken': 'ancien'})
