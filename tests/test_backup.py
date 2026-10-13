import json
import tempfile
import unittest
from pathlib import Path
from musicfinder.app import MusicFinder
from musicfinder.store import Store
from musicfinder.backup import export_backup, restore_backup


class BackupTests(unittest.TestCase):
    def test_saved_picks_restore_and_survive_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'musicfinder.db'
            app = MusicFinder(Store(path))
            app.set_pick('A favourite artist', 'love')
            app.store.set_setting('phone_key', 'keep-private')
            app.store.set_setting('lastfm_api_key', 'keep-private-key')
            app.store.put_blob('graph', {'artists': []})
            saved = export_backup(app)
            self.assertNotIn('keep-private', json.dumps(saved))
            app.clear('data')
            restore_backup(app, json.dumps(saved).encode())
            self.assertEqual(app.picks()['loved'], ['A favourite artist'])
            self.assertEqual(app.store.get_setting('phone_key'), 'keep-private')
            app.store.close()
            reopened = MusicFinder(Store(path))
            self.assertEqual(reopened.picks()['loved'], ['A favourite artist'])
            self.assertEqual(reopened.store.get_blob('graph'), {'artists': []})
            reopened.store.close()

    def test_invalid_restore_keeps_existing_data(self):
        app = MusicFinder(Store(':memory:'))
        app.set_pick('Keep this artist', 'love')
        good = export_backup(app)
        for bad in [{}, {**good, 'version': 2}, {**good, 'app': 'foreign'}, {**good, 'tables': {}}]:
            with self.assertRaises(ValueError): restore_backup(app, json.dumps(bad).encode())
        good['tables']['settings'].append(['phone_key', '"replacement"'])
        with self.assertRaises(ValueError): restore_backup(app, json.dumps(good).encode())
        self.assertEqual(app.picks()['loved'], ['Keep this artist'])
        app.store.close()

    def test_constraint_failure_rolls_back_all_tables(self):
        app = MusicFinder(Store(':memory:'))
        app.set_pick('Keep this artist', 'love')
        saved = export_backup(app)
        saved['tables']['library'] = [['picked_artist', None, '', None, None]]
        with self.assertRaises(ValueError): restore_backup(app, json.dumps(saved).encode())
        self.assertEqual(app.picks()['loved'], ['Keep this artist'])
        app.store.close()

    def test_demo_cannot_pretend_to_save_personal_data(self):
        app = MusicFinder(Store(':memory:'), demo=True)
        with self.assertRaises(ValueError): export_backup(app)
        app.store.close()


if __name__ == '__main__': unittest.main()
