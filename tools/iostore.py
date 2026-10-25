"""Minimal UE5 IoStore (.utoc/.ucas, TOC version 8) reader: directory index + chunk extraction."""
import struct
PAKS = r"C:\Program Files (x86)\Steam\steamapps\common\Star Wars Zero Company\SWZeroCompany\Content\Paks"

def be40(b): return int.from_bytes(b[:5], "big")

class Toc:
    def __init__(self, name):
        self.name = name
        d = open(PAKS + "\\" + name + ".utoc", "rb").read()
        assert d[:16] == b"-==--==--==--==-"
        (self.ver, _, _, hsz, n, ncb, cbsz, nm, mlen, self.blk, dsz, parts) = struct.unpack_from("<BBHIIIIIIIII", d, 16)
        self.flags = d[80]
        seeds, = struct.unpack_from("<I", d, 84)
        nohash, = struct.unpack_from("<I", d, 96)
        o = hsz
        self.ids = [d[o + 12*i: o + 12*i + 12] for i in range(n)]; o += 12*n
        self.offlen = [(be40(d[o+10*i:o+10*i+5]), be40(d[o+10*i+5:o+10*i+10])) for i in range(n)]; o += 10*n
        o += 4*seeds + 4*nohash
        self.blocks = []
        for i in range(ncb):
            b = d[o+12*i:o+12*i+12]
            self.blocks.append((int.from_bytes(b[0:5], "little"), int.from_bytes(b[5:8], "little"), int.from_bytes(b[8:11], "little"), b[11]))
        o += 12*ncb
        self.methods = [d[o+mlen*i:o+mlen*(i+1)].rstrip(b"\0").decode() for i in range(nm)]; o += mlen*nm
        if self.flags & 4:  # signed
            hs, = struct.unpack_from("<i", d, o); o += 4 + 2*hs + 20*ncb
        self.files = {}
        if self.flags & 8 and dsz:
            self._dirindex(d[o:o+dsz])
        self.ucas = open(PAKS + "\\" + name + ".ucas", "rb")

    def _dirindex(self, d):
        o = 0
        def fstr():
            nonlocal o
            n, = struct.unpack_from("<i", d, o); o += 4
            if n < 0:
                s = d[o:o-2*n].decode("utf-16le").rstrip("\0"); o += -2*n
            else:
                s = d[o:o+n].decode("latin-1").rstrip("\0"); o += n
            return s
        mount = fstr()
        nd, = struct.unpack_from("<i", d, o); o += 4
        dirs = [struct.unpack_from("<IIII", d, o + 16*i) for i in range(nd)]; o += 16*nd
        nf, = struct.unpack_from("<i", d, o); o += 4
        files = [struct.unpack_from("<III", d, o + 12*i) for i in range(nf)]; o += 12*nf
        ns, = struct.unpack_from("<i", d, o); o += 4
        strs = [fstr() for _ in range(ns)]
        NONE = 0xFFFFFFFF
        def walk(di, path):
            name, child, sib, ff = dirs[di]
            p = path + (strs[name] + "/" if name != NONE else "")
            f = ff
            while f != NONE:
                fn, nxt, ud = files[f]
                self.files[mount + p + strs[fn]] = ud
                f = nxt
            c = child
            while c != NONE:
                walk(c, p); c = dirs[c][2]
        walk(0, "")

    def read(self, idx):
        off, ln = self.offlen[idx]
        first, last = off // self.blk, (off + ln - 1) // self.blk
        out = bytearray()
        for bi in range(first, last + 1):
            boff, csz, usz, m = self.blocks[bi]
            self.ucas.seek(boff); raw = self.ucas.read((csz + 15) & ~15)[:csz]
            out += raw[:usz] if m == 0 else __import__("oodle").decompress(raw, usz)
        s = off - first * self.blk
        return bytes(out[s:s+ln])
