"""Minimal UE5.6 zen (IoStore) package header reader: name map, export map, import map."""
import struct
class Pkg:
    def __init__(self, b):
        self.b = b
        (self.hasVer, self.hsz, nidx, nnum, self.flags, self.cookedHsz, self.oHashes, self.oImports, self.oExports,
         self.oBundles, self.oDepH, self.oDepE, self.oPkgNames, self.oCellImp, self.oCellExp) = struct.unpack_from("<IIIIIIiiiiiiiii", b, 0)
        o = 60
        assert not self.hasVer, "versioning info not handled"
        self.names, o = self._names(o)
        self.name = self.names[nidx]
        self.imports = [struct.unpack_from("<Q", b, self.oImports + 8*i)[0] for i in range((self.oExports - self.oImports)//8)]
        n = (self.oCellImp - self.oExports) // 72
        self.exports = []
        for i in range(n):
            (off, size, ni, nn, outer, cls, sup, tmpl, pubhash, oflags, fflags) = struct.unpack_from("<QQIIQQQQQIB", b, self.oExports + 72*i)
            self.exports.append(dict(i=i, name=self.names[ni] + (f"_{nn-1}" if nn else ""), off=off, size=size,
                                     outer=outer, cls=cls, sup=sup, tmpl=tmpl, oflags=oflags))
    def _names(self, o):
        b = self.b
        n, = struct.unpack_from("<I", b, o); o += 4
        if n == 0: return [], o
        nbytes, = struct.unpack_from("<I", b, o); o += 4
        o += 8 + 8*n  # hash version + hashes
        hdr = b[o:o+2*n]; o += 2*n
        names = []
        for i in range(n):
            h0, h1 = hdr[2*i], hdr[2*i+1]
            wide = h0 & 0x80; ln = ((h0 & 0x7f) << 8) | h1
            if wide:
                if o & 1: o += 1
                names.append(b[o:o+2*ln].decode("utf-16le")); o += 2*ln
            else:
                names.append(b[o:o+ln].decode("latin-1")); o += ln
        return names, o
    def export_data(self, e):
        s = self.hsz + e["off"]
        return self.b[s:s+e["size"]]
    def idx_str(self, v):
        # FPackageObjectIndex: top 2 bits type (0 Export, 1 ScriptImport, 2 PackageImport, 3 Null)
        t = v >> 62
        if t == 3: return "null"
        if t == 0: return "export:" + self.exports[v & ((1<<62)-1)]["name"]
        if t == 2: return f"pkgimport:{(v>>32)&0x3fffffff}/{v & 0xffffffff}"
        return f"script:{v & ((1<<62)-1):x}"
