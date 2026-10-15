"""Small, read-only PE64 parser for function identities; no symbols are inferred."""
import bisect
import hashlib
from pathlib import Path
import struct


class PEIdentity:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        self.sha256 = hashlib.sha256(self.data).hexdigest()
        if self.data[:2] != b'MZ':
            raise ValueError('Not a PE image')
        nt = self.unpack('<I', 0x3c)[0]
        if self.data[nt:nt+4] != b'PE\0\0':
            raise ValueError('Bad PE signature')
        machine, count, _, _, _, optional, _ = self.unpack('<HHIIIHH', nt+4)
        o = nt+24
        if machine != 0x8664 or self.unpack('<H', o)[0] != 0x20b or count > 96 or optional < 240:
            raise ValueError('Expected bounded x64 PE32+')
        self.base = self.unpack('<Q', o+24)[0]
        self.size = self.unpack('<I', o+56)[0]
        self.sections = []
        for i in range(count):
            offset = o+optional+i*40
            name, size, rva, raw_size, raw = self.unpack('<8sIIII', offset)
            flags = self.unpack('<I', offset+36)[0]
            if raw+raw_size > len(self.data) or rva+size > self.size:
                raise ValueError('Section exceeds image')
            self.sections.append(dict(name=name.rstrip(b'\0').decode('ascii', errors='replace'),
                                      rva=rva, size=size, raw=raw, raw_size=raw_size, flags=flags))
        rva, size = self.unpack('<II', o+112+3*8)
        if size > 8*1024**2 or size % 12:
            raise ValueError('Invalid exception directory')
        pdata = self.bytes_at(rva, size) if size else b''
        self.functions = list(struct.iter_unpack('<III', pdata))
        if any(not (0 <= begin < end <= self.size and unwind < self.size)
               for begin, end, unwind in self.functions):
            raise ValueError('Invalid function bounds')
        self.starts = [f[0] for f in self.functions]
        if self.starts != sorted(set(self.starts)):
            raise ValueError('Unsorted or duplicate runtime functions')

    def unpack(self, fmt, offset):
        if offset < 0 or offset+struct.calcsize(fmt) > len(self.data):
            raise ValueError('Truncated PE')
        return struct.unpack_from(fmt, self.data, offset)

    def bytes_at(self, rva, size):
        if size < 0:
            raise ValueError('Negative size')
        for s in self.sections:
            delta = rva-s['rva']
            if 0 <= delta <= s['raw_size'] and size <= s['raw_size']-delta:
                return self.data[s['raw']+delta:s['raw']+delta+size]
        raise ValueError('RVA has no complete file-backed range')

    def function(self, rva):
        i = bisect.bisect_right(self.starts, rva)-1
        if i < 0 or rva >= self.functions[i][1]:
            return None
        begin, end, unwind = self.functions[i]
        code = self.bytes_at(begin, end-begin)
        return dict(begin_rva=begin, end_rva=end, unwind_rva=unwind,
                    signature=code[:32].hex(), code_sha256=hashlib.sha256(code).hexdigest())

    def catalog(self):
        # Strings are leads for disassembly. Finding a string does not identify
        # its handler, prove its ABI, or attribute any sample to it.
        leads = []
        for s in self.sections:
            raw = self.data[s['raw']:s['raw']+s['raw_size']]
            start = 0
            while True:
                found = raw.find(b'AvatarUpdate', start)
                if found < 0:
                    break
                string_start = raw.rfind(b'\0', 0, found)+1
                text = raw[string_start:string_start+200].split(b'\0')[0]
                if all(32 <= c < 127 for c in text):
                    leads.append(dict(rva=s['rva']+string_start, text=text.decode()))
                start = found+1
        return dict(executable_sha256=self.sha256, machine='amd64', image_size=self.size,
                    runtime_function_count=len(self.functions), avatar_string_leads=leads,
                    selected_patch=None, attribution_verified=False)
