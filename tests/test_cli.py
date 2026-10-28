"""The command line, exercised end to end on a database written here.

The fixture is the 40 inserts and 13 deletes of test_sqlite_wal, so the rows the
command must print are known, and the evidence files must come back unchanged.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlite_wal.__main__ import main  # noqa: E402
from test_sqlite_wal import WalFixture, _hashes  # noqa: E402


class CliTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        fixture = WalFixture(self.tmp)
        fixture.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, txt TEXT)')
        fixture.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        for i in range(1, 41):
            fixture.execute('INSERT INTO t VALUES (?, ?)', (i, 'row %d' % i))
        for i in range(5, 18):
            fixture.execute('DELETE FROM t WHERE id = ?', (i,))
        fixture.execute("UPDATE t SET txt = 'tab\there' WHERE id = 1")
        self.evidence = fixture.evidence
        self.db = fixture.capture()
        self.before = _hashes(self.evidence)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        stdout, stderr, sys.stdout, sys.stderr = sys.stdout, sys.stderr, out, err
        try:
            code = main(list(argv))
        finally:
            sys.stdout, sys.stderr = stdout, stderr
        return code, out.getvalue(), err.getvalue()

    def test_rows_prints_every_deleted_row_and_the_earlier_version(self):
        code, text, err = self.run_cli('rows', self.db, '--query', 'SELECT id, txt FROM t',
                                       '--key', '0')
        self.assertEqual(code, 0)
        lines = text.splitlines()
        self.assertEqual(lines[0].split('\t'),
                         ['status', 'first state', 'last state', 'first frame', 'last frame',
                          'earlier generation', 'uncommitted', 'id', 'txt'])
        records = [line.split('\t') for line in lines[1:]]
        # Every line keeps its column count, including the value holding a tab.
        self.assertTrue(all(len(record) == 9 for record in records))
        deleted = sorted(int(r[7]) for r in records if r[0] == 'Not in current state')
        self.assertEqual(deleted, list(range(5, 18)))
        earlier = [r for r in records if r[0] == 'Earlier version of a current row']
        self.assertEqual([(r[7], r[8]) for r in earlier], [('1', 'row 1')])
        self.assertIn('committed transactions', err)
        self.assertEqual(_hashes(self.evidence), self.before)

    def test_summary_lists_the_current_state_first(self):
        code, text, _err = self.run_cli('summary', self.db)
        self.assertEqual(code, 0)
        lines = text.splitlines()
        self.assertIn('t.db: ', lines[0])
        self.assertEqual(lines[2], 'kind\tstate\tlast frame')
        self.assertTrue(lines[3].startswith('current\t'))
        self.assertTrue(all(line.startswith('committed\t') for line in lines[4:]))
        self.assertEqual(_hashes(self.evidence), self.before)

    def test_a_database_without_a_log_says_so(self):
        os.unlink(self.db + '-wal')
        code, text, _err = self.run_cli('summary', self.db)
        self.assertEqual(code, 0)
        self.assertEqual(text.strip(), 't.db: no write-ahead log beside the database')

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_cli('summary', os.path.join(self.tmp, 'absent.db'))
        self.assertEqual(raised.exception.code, 2)

    def test_a_closed_pipe_ends_quietly(self):
        reader, writer = os.pipe()
        os.close(reader)
        result = subprocess.run(
            [sys.executable, '-m', 'sqlite_wal', 'rows', self.db,
             '--query', 'SELECT id, txt FROM t'],
            cwd=ROOT_DIR, stdin=subprocess.DEVNULL, stdout=writer, stderr=subprocess.PIPE)
        os.close(writer)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(b'Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
