"""Verify a research snapshot using only the Python 3.6+ standard library."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    errors, seen = [], set()
    for row in manifest['files']:
        relative = PurePosixPath(row['path'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in row['path'] or ':' in row['path']:
            errors.append({'path': row['path'], 'error': 'unsafe path'})
            continue
        target = root.joinpath(*relative.parts)
        if row['path'] in seen or root not in target.resolve().parents:
            errors.append({'path': row['path'], 'error': 'duplicate or escaped path'})
            continue
        seen.add(row['path'])
        if target.is_symlink() or not target.is_file():
            errors.append({'path': row['path'], 'error': 'missing or linked file'})
        elif target.stat().st_size != row['bytes'] or digest(target) != row['sha256']:
            errors.append({'path': row['path'], 'error': 'size or SHA256 mismatch'})
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    unexpected = sorted(actual - seen - {'manifest.json'})
    return {'ok': not errors and not unexpected, 'files_checked': len(seen),
            'bytes': sum(row['bytes'] for row in manifest['files']),
            'errors': errors, 'unexpected_files': unexpected,
            'manifest_sha256': digest(root / 'manifest.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', nargs='?', default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    result = verify(args.folder)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
