#!/usr/bin/env python3
"""Verify exact driver archive hits and original rendering fallback; no gameplay capture."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from build_runtime import ROOT, sha


def verify(output):
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    binary=output/'metal_archive_probe'
    subprocess.run(['xcrun','clang++','-std=c++17','-O2','-mmacosx-version-min=13.0','-framework','Metal','-framework','Foundation',
                    str(ROOT/'tests/metal_archive_probe.mm'),'-o',str(binary)],check=True)
    cache=output/'cache'
    env={k:v for k,v in os.environ.items() if not k.startswith('W101_')}
    env.update(W101_METAL_ARCHIVE='1',W101_METAL_ARCHIVE_PATH=str(cache),W101_METAL_ARCHIVE_KEY='a'*64)
    checks={}
    def run(name,mode,**changes):
        result=subprocess.run([str(binary),mode],env=env|changes,text=True,capture_output=True,timeout=60)
        row=json.loads(result.stdout)
        if result.returncode or not row['passed']:raise RuntimeError(f'{name} failed: {result.stdout} {result.stderr}')
        checks[name]=row
    run('default_off_original_pixels','fallback',W101_METAL_ARCHIVE='0')
    if cache.exists():raise ValueError('Disabled archive created files')
    run('create_exact_archive','create')
    archive,=cache.glob('*.metalar')
    original=sha(archive)
    run('separate_process_driver_confirmed_hit','warm')
    run('changed_renderer_identity_rejected','mismatch',W101_METAL_ARCHIVE_KEY='b'*64)
    run('invalid_mode_original_pixels','fallback',W101_METAL_ARCHIVE='invalid')
    run('invalid_key_original_pixels','fallback',W101_METAL_ARCHIVE_KEY='not-a-hash')
    unavailable=output/'not-a-directory';unavailable.write_text('file')
    run('unavailable_storage_original_pixels','fallback',W101_METAL_ARCHIVE_PATH=str(unavailable))
    run('failed_save_original_pixels','save-failure')
    if sha(archive)!=original:raise ValueError('Failed save changed the prior archive')
    checks['failed_save_preserves_previous_bytes']=True
    archive.write_bytes(b'invalid Metal archive')
    run('corrupt_archive_original_pixels_and_rebuild','create')
    run('rebuilt_archive_driver_confirmed_hit','warm')
    with archive.open('wb') as f:f.truncate(64*1024*1024+1)
    run('oversize_archive_rebuilt','create')
    run('oversize_recovery_driver_confirmed_hit','warm')
    if list(cache.glob('*.tmp.*')):raise ValueError('Temporary archive leaked')
    report=dict(passed=True,synthetic_only=True,gameplay_performance_verified=False,checks=checks,
                inputs={n:sha(ROOT/n) for n in ['performance/MetalArchive.h','tests/metal_archive_probe.mm','verify_metal_archive.py']},
                probe_sha256=sha(binary),archive_sha256=sha(archive),archive_bytes=archive.stat().st_size,
                gameplay_logging_added=False,capture_run=False)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    print(json.dumps(verify(p.parse_args().output),indent=2))
