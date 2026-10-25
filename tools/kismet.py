"""Minimal UE5 Kismet bytecode reader for cooked zen packages.
Tracks both the on-disk position and the in-memory offset (jump targets use memory offsets:
object pointers and property pointers are 8 bytes, FScriptName is 12 bytes in memory)."""
import struct, ctypes

_hash = None
def script_hash(path):
    """FPackageObjectIndex for a /Script path, using the game's own CityHash64."""
    global _hash
    if _hash is None:
        import oodle
        _hash = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_void_p, ctypes.c_uint32)(oodle.base + 0x4200080)
    s = path.lower().replace('.', '/').replace(':', '/').encode('utf-16le')
    return (_hash(s, len(s)) & ~(3 << 62)) | (1 << 62)

class Ex(Exception): pass

class Reader:
    def __init__(self, pkg, data):
        self.p, self.d, self.o, self.m = pkg, data, 0, 0
        self.calls = []  # (mem_offset, kind, target)
    def u8(self):  v = self.d[self.o]; self.o += 1; self.m += 1; return v
    def u16(self): v, = struct.unpack_from("<H", self.d, self.o); self.o += 2; self.m += 2; return v
    def i32(self): v, = struct.unpack_from("<i", self.d, self.o); self.o += 4; self.m += 4; return v
    def u32(self): v, = struct.unpack_from("<I", self.d, self.o); self.o += 4; self.m += 4; return v
    def skip(self, n): self.o += n; self.m += n
    def obj(self):
        v, = struct.unpack_from("<i", self.d, self.o); self.o += 4; self.m += 8
        return self.ref(v)
    def ref(self, v):
        if v > 0: return "export:" + self.p.exports[v-1]["name"]
        if v < 0:
            imp = self.p.imports[-v-1]
            return ("imp", imp)
        return None
    def name(self):
        i, n = struct.unpack_from("<II", self.d, self.o); self.o += 8; self.m += 12
        return self.p.names[i] if i < len(self.p.names) else f"?name{i}"
    def prop(self):
        n, = struct.unpack_from("<i", self.d, self.o); self.o += 4
        path = []
        for _ in range(n):
            i, num = struct.unpack_from("<II", self.d, self.o); self.o += 8
            path.append(self.p.names[i] if i < len(self.p.names) else "?")
        self.o += 4  # owner (always serialized)
        self.m += 8
        return ".".join(path)
    def zstr(self, wide=False):
        if wide:
            e = self.o
            while self.d[e:e+2] != b"\0\0": e += 2
            s = self.d[self.o:e].decode("utf-16le"); n = e + 2 - self.o
        else:
            e = self.d.index(b"\0", self.o); s = self.d[self.o:e].decode("latin-1"); n = e + 1 - self.o
        self.o += n; self.m += n; return s

    def params(self):
        while True:
            if self.d[self.o] == 0x16: self.u8(); return
            self.expr()

    def expr(self):
        at = self.m
        t = self.u8()
        E = self.expr
        if t in (0x00, 0x01, 0x02, 0x48, 0x33, 0x6C): self.prop()
        elif t == 0x04: E()
        elif t == 0x06: self.u32()
        elif t == 0x07: self.u32(); E()
        elif t == 0x09: self.u16(); self.u8(); E()
        elif t in (0x0B, 0x15, 0x16, 0x17, 0x25, 0x26, 0x27, 0x28, 0x2A, 0x2D, 0x30, 0x32, 0x3A, 0x3C, 0x3E, 0x40, 0x4D, 0x50, 0x53, 0x5A, 0x5E, 0x66, 0x4A): pass
        elif t == 0x0C: self.i32()
        elif t == 0x0F: self.prop(); E(); E()
        elif t == 0x11: self.prop(); self.u8()
        elif t in (0x12, 0x19, 0x1A): E(); self.u32(); self.prop(); E()
        elif t in (0x13, 0x2E, 0x52, 0x54, 0x55): self.obj(); E()
        elif t in (0x14, 0x43, 0x44, 0x5C, 0x5F, 0x60, 0x62, 0x6B): E(); E()
        elif t == 0x18: self.u32(); E()
        elif t in (0x1B, 0x45):
            n = self.name(); self.calls.append((at, "virtual", n)); self.params()
        elif t in (0x1C, 0x46, 0x68):
            f = self.obj(); self.calls.append((at, "final", f)); self.params()
        elif t == 0x63:
            f = self.obj(); self.calls.append((at, "delegate", f)); self.params()
        elif t == 0x1D: self.i32()
        elif t == 0x1E: self.skip(4)
        elif t == 0x1F: self.zstr()
        elif t == 0x34: self.zstr(True)
        elif t == 0x20: self.obj()
        elif t == 0x21: self.name()
        elif t in (0x22, 0x23): self.skip(24)
        elif t == 0x41: self.skip(12)
        elif t == 0x2B: self.skip(80)
        elif t in (0x24, 0x2C): self.u8()
        elif t in (0x35, 0x36, 0x37): self.skip(8)
        elif t == 0x29:
            k = self.u8()
            if k == 0: pass
            elif k == 1: E(); E(); E()
            elif k in (2, 3): E()
            elif k == 4: self.obj(); E(); E()
            elif k == 0xFF: pass
            else: raise Ex(f"text kind {k}")
        elif t == 0x2F:
            self.obj(); self.i32()
            while self.d[self.o] != 0x30: E()
            self.u8()
        elif t == 0x31:
            E()
            while self.d[self.o] != 0x32: E()
            self.u8()
        elif t in (0x39, 0x3B):
            E(); self.i32(); end = 0x3A if t == 0x39 else 0x3C
            while self.d[self.o] != end: E()
            self.u8()
        elif t == 0x3D:
            self.prop(); self.i32()
            while self.d[self.o] != 0x3E: E()
            self.u8()
        elif t == 0x3F:
            self.prop(); self.prop(); self.i32()
            while self.d[self.o] != 0x40: E()
            self.u8()
        elif t == 0x65:
            self.prop(); self.i32()
            while self.d[self.o] != 0x66: E()
            self.u8()
        elif t == 0x42: self.prop(); E()
        elif t == 0x38: self.u8(); E()
        elif t == 0x4B: self.name()
        elif t == 0x4C: self.u32()
        elif t in (0x4E, 0x4F, 0x51, 0x5D, 0x67, 0x6D): E()
        elif t == 0x5B: self.u32()
        elif t == 0x61: self.name(); E(); E()
        elif t == 0x64: self.prop(); E()
        elif t == 0x69:
            n = self.u16(); self.u32(); E()
            for _ in range(n): E(); self.u32(); E()
            E()
        elif t == 0x6A:
            k = self.u8()
            if k == 4: self.name()  # InlineEvent
        else:
            raise Ex(f"unknown token {t:#x} at disk {self.o-1:#x}")
        return t

def find_scripts(data):
    """Candidate (start, memsize, disksize, tail) of the bytecode inside a UFunction export, best first."""
    out = []
    for s in range(0, len(data) - 8):
        mem, disk = struct.unpack_from("<ii", data, s)
        if 0 < disk and 0 < mem <= 4 * disk and s + 8 + disk <= len(data) and data[s + 8 + disk - 1] == 0x53:
            tail = len(data) - (s + 8 + disk)
            if tail <= 24: out.append((s + 8, mem, disk, tail))
    return sorted(out, key=lambda c: (c[3], -c[2]))

def find_script(data):
    c = find_scripts(data); return c[0] if c else None

def _parse(pkg, code, mem):
    r = Reader(pkg, code)
    stmts = []
    while r.o < len(code):
        at = r.m
        t = r.expr()
        stmts.append((at, t))
        if t == 0x53: break
    if r.o != len(code) or r.m != mem: raise Ex("size mismatch")
    return r, stmts

def disassemble(pkg, export):
    data = pkg.export_data(export)
    err = None
    for start, mem, disk, _ in find_scripts(data):
        try:
            return _parse(pkg, data[start:start+disk], mem)
        except Exception as x:
            err = x
    if err: raise err
    return None
