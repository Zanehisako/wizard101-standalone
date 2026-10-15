#!/usr/bin/env python3
"""Check the compiled cache namespace fingerprints current translation sources."""
import hashlib
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent/'source/src'
files=list((ROOT/'dxso').rglob('*'))+list((ROOT/'spirv').rglob('*'))+list((ROOT/'dxvk').glob('dxvk_shader*'))+list((ROOT/'d3d9').glob('d3d9_shader*'))
h=hashlib.sha256()
for p in sorted(set(files)):
    if p.is_file(): h.update(str(p.relative_to(ROOT)).encode()); h.update(p.read_bytes())
expected='#pragma once\n#define W101_SHADER_REVISION "'+h.hexdigest()+'"\n'
path=ROOT/'util/util_shader_revision.h'
if '--update' in sys.argv: path.write_text(expected)
else:
    assert path.read_text()==expected,'Shader translation revision changed; update fingerprint and regenerate wizard101.patch'
print(h.hexdigest())
