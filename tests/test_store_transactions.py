"""Actual SQLite rollback and persistence, without native model work."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dashboard.store import Store


class StoreTransactionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name).resolve() / 'state'
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_operation_task_and_link_survive_reopen_together(self):
        self.store.put('obsolete', {'id': 'old'})
        self.store.put_many([('task', {'id': 'task', 'status': 'queued'}),
                             ('operation', {'id': 'operation', 'status': 'prepared'}),
                             ('link', {'id': 'link', 'task_id': 'task'})],
                            deletes=[('obsolete', 'old')])
        reopened = Store(self.path)
        try:
            self.assertEqual('queued', reopened.load('task')[0]['status'])
            self.assertEqual('prepared', reopened.load('operation')[0]['status'])
            self.assertEqual('task', reopened.load('link')[0]['task_id'])
            self.assertEqual([], reopened.load('obsolete'))
        finally:
            reopened.close()

    def test_failed_database_write_rolls_back_prior_write_and_delete(self):
        self.store.put('task', {'id': 'task', 'status': 'unknown'})
        self.store.put('retained', {'id': 'old'})
        self.store.db.execute("CREATE TRIGGER reject_operation BEFORE INSERT ON records "
                              "WHEN NEW.kind='operation' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        self.store.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.put_many([('task', {'id': 'task', 'status': 'queued'}),
                                 ('operation', {'id': 'operation'})],
                                deletes=[('retained', 'old')])
        self.assertEqual('unknown', self.store.load('task')[0]['status'])
        self.assertEqual([{'id': 'old'}], self.store.load('retained'))
        self.assertEqual([], self.store.load('operation'))

    def test_encoding_failure_never_begins_partial_update(self):
        self.store.put('retained', {'id': 'old'})
        with self.assertRaises(ValueError):
            self.store.put_many([('task', {'id': 'task'}),
                                 ('operation', {'id': 'operation', 'value': float('nan')})],
                                deletes=[('retained', 'old')])
        self.assertEqual([], self.store.load('task'))
        self.assertEqual([{'id': 'old'}], self.store.load('retained'))
