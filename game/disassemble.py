#!/usr/bin/env python3
"""Read-only function disassembly, with PE import and literal references."""
import argparse
from pathlib import Path
import capstone
import pefile
from pe_identity import PEIdentity

def disassemble(path, rva):
    identity = PEIdentity(path)
    function = identity.function(rva)
    if function is None:
        raise ValueError('Address has no recorded runtime function')
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
    imports = {entry.address: (module.dll.decode(errors='replace')+'!'+(entry.name.decode(errors='replace') if entry.name else str(entry.ordinal)))
               for module in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []) for entry in module.imports}
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); cs.detail = True
    print('Function', hex(function['begin_rva']), hex(function['end_rva']), 'SHA256', function['code_sha256'])
    for insn in cs.disasm(identity.bytes_at(function['begin_rva'], function['end_rva']-function['begin_rva']), identity.base+function['begin_rva']):
        annotations = []
        for op in insn.operands:
            address = op.imm if op.type == capstone.x86.X86_OP_IMM else insn.address+insn.size+op.mem.disp if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP else 0
            if address in imports:
                annotations.append(imports[address])
            elif identity.base <= address < identity.base+identity.size:
                annotations.append('rva='+hex(address-identity.base))
                try:
                    text = identity.bytes_at(address-identity.base, 200).split(b'\0')[0]
                    if len(text) > 2 and all(32 <= b < 127 for b in text):
                        annotations.append(text.decode())
                except ValueError:
                    pass
        print(hex(insn.address-identity.base), insn.mnemonic, insn.op_str, '; '+' | '.join(annotations) if annotations else '')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('rva', type=lambda text: int(text, 0))
    args = parser.parse_args()
    disassemble(args.exe, args.rva)
