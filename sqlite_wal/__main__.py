"""Command line for sqlite-wal.

    python -m sqlite_wal summary DB                    what the log holds and which states read
    python -m sqlite_wal rows DB --query SQL           rows another state holds and the current does not
    python -m sqlite_wal rows DB --query SQL --key 0   label rows whose key is still present

DB is the database file; its -wal is read from beside it. Neither is written: each
state is read from a scratch copy that is removed on exit.

One database and one query at a time, on purpose. A recovered row only means
something next to the live rows of the same table, read the same way.
"""

import argparse
import os
import sys
from importlib import metadata

from . import (KIND_COMMITTED, KIND_EARLIER, KIND_UNCOMMITTED, DEFAULT_MAX_STATES,
               WalStates, rows_not_in_current)

KINDS = {'earlier': KIND_EARLIER, 'uncommitted': KIND_UNCOMMITTED}


def _version():
    try:
        return metadata.version('sqlite-wal')
    except metadata.PackageNotFoundError:
        return 'not installed'


def _include(names):
    include = [KIND_COMMITTED]
    for name in names or ():
        include.append(KINDS[name])
    return tuple(include)


def _cell(value):
    if value is None:
        return ''
    if isinstance(value, (bytes, bytearray)):
        return '<' + str(len(value)) + ' bytes> ' + bytes(value).hex()
    text = str(value)
    return text.replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')


def _summary(args, out):
    with WalStates(args.db, max_states=args.max_states, include=_include(args.include)) as wal:
        listed = [(state.kind, state.number, state.frame) for state in wal.states()]
        # summary() counts what states() met, so it is read after the walk.
        print(wal.summary(), file=out)
    if listed:
        print('', file=out)
        print('kind\tstate\tlast frame', file=out)
        for position, (kind, number, frame) in enumerate(listed):
            label = 'current' if position == 0 else kind
            print(f'{label}\t{number}\t{frame}', file=out)
    return 0


def _rows(args, out):
    columns, rows, wal = rows_not_in_current(
        args.db, args.query, key_columns=args.key or None,
        max_states=args.max_states, include=_include(args.include))
    print(wal.summary(), file=sys.stderr)
    header = ['status', 'first state', 'last state', 'first frame', 'last frame',
              'earlier generation', 'uncommitted'] + list(columns)
    print('\t'.join(_cell(name) for name in header), file=out)
    for row in rows:
        earlier = (f'{row.earlier_generation[0]}-{row.earlier_generation[1]}'
                   if row.earlier_generation else '')
        cells = [row.status, row.first_state, row.last_state, row.first_frame, row.last_frame,
                 earlier, 'yes' if row.uncommitted else ''] + list(row.values)
        print('\t'.join(_cell(cell) for cell in cells), file=out)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='sqlite-wal', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version', action='version', version=f'%(prog)s {_version()}')
    commands = parser.add_subparsers(dest='command', required=True)

    def common(sub):
        sub.add_argument('db', help='the database file; its -wal is read from beside it')
        sub.add_argument('--include', action='append', choices=sorted(KINDS),
                         help='also read the previous log generation (earlier) or frames '
                              'after the last commit (uncommitted); repeatable')
        sub.add_argument('--max-states', type=int, default=DEFAULT_MAX_STATES,
                         help=f'read at most this many committed states (default '
                              f'{DEFAULT_MAX_STATES})')

    common(commands.add_parser('summary', help='what the log holds and which states are read'))
    rows = commands.add_parser('rows', help='rows a query returns in another state and not '
                                            'in the current one, tab separated')
    common(rows)
    rows.add_argument('--query', required=True, help='one SELECT, run in every state')
    rows.add_argument('--key', type=int, action='append', metavar='INDEX',
                      help='index of a result column that identifies a row; a row whose key '
                           'the current state still holds is labelled an earlier version; '
                           'repeatable')

    args = parser.parse_args(argv)
    if not os.path.isfile(args.db):
        parser.error(f'not a file: {args.db}')
    handler = _summary if args.command == 'summary' else _rows
    try:
        code = handler(args, sys.stdout)
        sys.stdout.flush()
        return code
    except BrokenPipeError:
        # A reader such as head closed the pipe; stop quietly, as cat does.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0


if __name__ == '__main__':
    sys.exit(main())
