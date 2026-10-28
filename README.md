# sqlite-wal

Read the earlier states of a SQLite database that its write-ahead log still
holds, for digital forensics. One module, standard library only, which is what
lets the LEAPP tools vendor it as a single file.

```
python -m sqlite_wal summary DB                                  what the log holds, which states are read
python -m sqlite_wal rows DB --query "SELECT id, body FROM t"    rows another state holds and the current one does not
python -m sqlite_wal rows DB --query "..." --key 0               also label rows whose key the current state still has
python -m sqlite_wal rows DB --query "..." --include earlier     also read the previous log generation
```

`DB` is the database file. Its `-wal` is read from beside it. `rows` prints tab
separated values to standard output and the summary line to standard error.

As a library:

```python
from sqlite_wal import WalStates, rows_not_in_current

columns, rows, wal = rows_not_in_current(db_path, 'SELECT id, body FROM messages',
                                         key_columns=[0])
for row in rows:
    print(row.status, row.first_state, row.last_state, row.values)
print(wal.summary())

with WalStates(db_path) as wal:            # every readable state, current first
    for state in wal.states():
        state.connection.execute(...)
```

## How it reads a state

A database in WAL mode appends each committed transaction to `<db>-wal` as
frames, and a checkpoint later copies them into the database file. Until the log
is reset, the frames of earlier transactions stay in it, so the log holds every
committed state since the last reset, not just the newest one.

For each commit in the current log generation, a scratch copy of the database
and its log is made, the log copy is cut at the end of that commit, and the copy
is opened read-only. SQLite then applies its own salt, checksum and commit rules
to the frames that remain. Nothing here decodes records from bytes: every row
comes from SQLite running a query against a state.

Two more kinds of state are read only when asked for:

- **earlier**: frames the previous log generation left behind when the current
  one did not overwrite them. These are rebuilt by writing the page images onto
  a scratch copy of the database file, and read only when every gate in the
  module docstring holds and SQLite's `quick_check` passes.
- **uncommitted**: frames after the last commit, from a transaction that had not
  committed when the files were copied.

The evidence files are only read. The tests check that they hash the same after a run.

## What a result means, and what it does not

**A row from `rows` was present in an earlier state and is absent from the
current one.** That is all it says. An app trimming a rolling table, a
rewrite that changes one column, and a user deleting a record all give the same
result. Use `--key` so a row whose key is still present is labelled
`Earlier version of a current row` rather than `Not in current state`.

**Rows compare by every value the query returns.** A schema change partway
through the log can make one record read as two.

**Not read, and counted in the summary:** frames of generations older than the
previous one, frames after a checksum break, and the oldest states over
`--max-states`. **Not read at all:** freelist pages, freeblocks and unallocated
space in the database file, and rollback journals. A log that was checkpointed
and truncated holds nothing to read, so an empty result is not evidence that
nothing was deleted.

**A checkpoint limits what can be rebuilt.** Once a checkpoint has copied part
of the log into the database file, an earlier state can only be read where every
page the checkpoint wrote also has an image earlier in the log. States that fail
that test are skipped and counted, never rebuilt from a mix of times.

## Tests

```
python -m unittest discover -s tests -p 'test_*.py' -v
```

Every fixture is written by the tests with known data: the rows inserted,
deleted and changed are known, so the result is checked against them exactly,
and the newest state must equal what SQLite itself reads from an untouched copy
of the full log. CI runs Python 3.10 to 3.14 and fails on any skipped test.

## Used by

ALEAPP, iLEAPP, RLEAPP, VLEAPP and DLEAPP carry this module as
`scripts/sqlite_wal.py`, under a banner naming the commit it was copied at.
Their `admin/scripts/check_vendored.py` fetches this repository's file at that
commit and fails CI when the copy differs. Fix it here and re-vendor; an edit
made in a copy is reverted by the next sync.

Format reference: https://www.sqlite.org/fileformat2.html#the_write_ahead_log

## License

MIT. See [LICENSE](LICENSE).
