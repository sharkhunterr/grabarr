#!/usr/bin/env bash
# Wipe the downloads history + on-disk staging files. Keeps profiles,
# settings, adapter credentials, API keys untouched.
#
# Usage:
#   ./reset-downloads.sh
#   ./reset-downloads.sh --yes   # skip the confirm prompt

set -e

cd "$(dirname "$0")"

if [ "${1:-}" != "--yes" ]; then
    printf 'This will DELETE:\n'
    printf '  - every row in downloads / torrents / search_tokens / search_cache\n'
    printf '  - every staged file under downloads/ready and downloads/incoming\n'
    printf '  - every /tmp/grabarr-aa-* scratch dir\n'
    printf '\nContinue? [y/N] '
    read -r ans
    case "$ans" in y|Y|yes|YES) ;; *) echo "aborted"; exit 1 ;; esac
fi

uv run python -c "
import asyncio, shutil
from pathlib import Path
from sqlalchemy import text
from grabarr.db.session import session_scope

async def main():
    async with session_scope() as s:
        for tbl in ('torrents', 'downloads', 'search_tokens', 'search_cache'):
            await s.execute(text(f'DELETE FROM {tbl}'))
        await s.commit()

asyncio.run(main())

for d in (Path('downloads/ready'), Path('downloads/incoming')):
    if d.exists():
        for c in d.iterdir():
            if c.is_dir(): shutil.rmtree(c, ignore_errors=True)
            else: c.unlink(missing_ok=True)

for tmp in Path('/tmp').glob('grabarr-aa-*'):
    shutil.rmtree(tmp, ignore_errors=True)

print('[reset] downloads + staging cleared')
"
