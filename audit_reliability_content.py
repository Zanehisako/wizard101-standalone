#!/usr/bin/env python3
"""Read-only content audit. Header-valid streamed/sparse WADs are never called corrupt."""
import argparse
import json
from pathlib import Path
import zlib


def crc(path, count):
    value = 0
    with path.open('rb') as stream:
        while count:
            data = stream.read(min(count, 1024 * 1024))
            if not data:
                return None
            value = zlib.crc32(data, value ^ 0xffffffff) ^ 0xffffffff
            count -= len(data)
    return value


def inspect(root):
    root = Path(root).resolve()
    game = root / 'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101'
    cache = json.loads((root / 'State/checksums.json').read_text())
    files = {}
    for relative, entry in cache.get('entries', {}).items():
        path = game / relative
        if path.is_symlink() or not path.resolve().is_relative_to(game.resolve()):
            raise ValueError('Content cache path leaves the game installation')
        validation = entry['validation']
        mode = validation['mode']
        if mode not in ('fullFile', 'archiveHeader'):
            raise ValueError('Unknown checksum validation mode')
        if not path.is_file():
            files[relative] = {'status': 'missing_cached_file', 'validation': validation}
            continue
        info = path.stat()
        size_matches = info.st_size == entry['size']
        measured = crc(path, validation['bytes'])
        valid = size_matches and measured == validation['crc']
        files[relative] = dict(status='matches_cached_manifest' if valid else 'needs_current_manifest_check',
                               validation=validation, logical_bytes=info.st_size, allocated_bytes=info.st_blocks * 512,
                               header_only=mode == 'archiveHeader', sparse=info.st_blocks * 512 < info.st_size)
    return files


def audit(fresh, existing):
    fresh, existing = inspect(fresh), inspect(existing)
    shared = sorted(fresh.keys() & existing.keys())
    comparable = [name for name in shared if fresh[name]['validation'] == existing[name]['validation']]
    result = {'read_only': True, 'gameplay_verified': False, 'files_modified': False,
              'validation': 'Cached official checksums are re-read; a mismatch needs the current manifest. Streamed archives use header CRC, never full-file CRC over sparse holes.',
              'fresh': fresh, 'existing_summary': {
                  'cached_files': len(existing), 'matching_files': sum(f['status'] == 'matches_cached_manifest' for f in existing.values()),
                  'needs_current_manifest_check': [name for name, f in existing.items() if f['status'] != 'matches_cached_manifest']},
              'comparison': {'shared_paths': len(shared), 'same_expected_checksums': len(comparable),
                  'both_match': sum(fresh[name]['status'] == existing[name]['status'] == 'matches_cached_manifest' for name in comparable),
                  'different_cached_expectations': [name for name in shared if name not in comparable]}}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fresh-data-root', type=Path, required=True)
    parser.add_argument('--existing-data-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.fresh_data_root, args.existing_data_root)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'fresh_files': len(report['fresh']), 'existing': report['existing_summary'], 'comparison': report['comparison']}))
