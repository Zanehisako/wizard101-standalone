#!/usr/bin/env python3
"""Optional Capstone-assisted static leads; never choose a hook from a string alone."""
import argparse
import json
from pathlib import Path
import re
import struct
import capstone
from pe_identity import PEIdentity


def catalog(exe):
    pe = PEIdentity(exe)
    result = pe.catalog()
    strings = {s['rva']: s['text'] for s in result['avatar_string_leads']}
    candidates = {}
    for section in pe.sections:
        if not section['flags'] & 0x20000000:
            continue
        raw = pe.data[section['raw']:section['raw']+section['raw_size']]
        # Restrict candidate generation to RIP-relative LEA/MOV. Validate every
        # candidate by decoding from its recorded runtime-function boundary.
        for match in re.finditer(rb'[\x48-\x4f][\x8d\x8b][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]', raw):
            offset = match.start()
            if offset+7 > len(raw):
                continue
            rva = section['rva']+offset
            target = rva+7+struct.unpack_from('<i', raw, offset+3)[0]
            if target not in strings:
                continue
            function = pe.function(rva)
            if function:
                candidates.setdefault(function['begin_rva'], []).append((rva, target))
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    cs.detail = True
    xrefs = []
    for begin, leads in candidates.items():
        identity = pe.function(begin)
        instructions = {insn.address-pe.base: insn for insn in cs.disasm(
            pe.bytes_at(begin, identity['end_rva']-begin), pe.base+begin)}
        for rva, target in leads:
            insn = instructions.get(rva)
            if not insn:
                continue
            actual = [insn.address+insn.size+op.mem.disp-pe.base for op in insn.operands
                      if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP]
            if target in actual:
                xrefs.append(dict(string=strings[target], string_rva=target, instruction_rva=rva,
                                  instruction=insn.mnemonic+' '+insn.op_str, function=identity,
                                  role='String-reference function; handler role and ABI remain unverified'))
    result['avatar_instruction_xrefs'] = xrefs
    result['capstone_version'] = capstone.__version__
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('exe', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    with a.output.open('x') as f:
        json.dump(catalog(a.exe), f, indent=2)
        f.write('\n')
