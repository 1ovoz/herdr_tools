"""Small, private JSONL log. Records only identifiers and stage codes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

FEATURES = {'usage', 'transfer', 'pdf', 'tabs', 'installer'}


def safe(value):
    return value if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', value or '') else 'unknown'


def record(root, feature, stage, code, job=None):
    if feature not in FEATURES:
        return
    try:
        folder = Path(root) / 'data' / 'herdr-mod-kit' / 'logs'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{feature}.jsonl'
        try:
            if path.stat().st_size > 512 * 1024:
                path.replace(path.with_suffix('.previous.jsonl'))
        except FileNotFoundError:
            pass
        row = {'utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'feature': feature,
               'stage': safe(stage), 'code': safe(code)}
        if job:
            row['job'] = safe(job)
        with path.open('a', encoding='utf8') as out:
            out.write(json.dumps(row, separators=(',', ':')) + '\n')
    except OSError:
        # Diagnostics must never prevent a read or transfer from completing.
        print(f'[herdr-kit/{feature}] log_write_failed', file=sys.stderr)


if __name__ == '__main__':
    record(*sys.argv[1:])
