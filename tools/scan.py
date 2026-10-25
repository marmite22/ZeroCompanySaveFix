"""Scan every gameplay ability Blueprint for presentation overrides that never let the native
StopPresentation run (which is what tells the save blocker the ability's animation finished)."""
import re, struct, sys, json
import iostore, zen, kismet, hashdb

H = hashdb.build()
TOCS = [iostore.Toc("pakchunk0-Windows"), iostore.Toc("pakchunk1-Windows")]
INDEX = {}
for t in TOCS:
    for p, i in t.files.items(): INDEX[p] = (t, i)

def game_to_file(pkgname):
    if pkgname.startswith("/Game/"): return "../../../SWZeroCompany/Content/" + pkgname[6:] + ".uasset"
    return None

_pk = {}
def load(pkgname):
    if pkgname in _pk: return _pk[pkgname]
    f = game_to_file(pkgname); p = None
    if f and f in INDEX:
        t, i = INDEX[f]
        p = zen.Pkg(t.read(i)); p.pkgnames, _ = p._names(p.oPkgNames) if p.oPkgNames < p.hsz else ([], 0)
        p.pubhashes = [struct.unpack_from("<Q", p.b, p.oHashes + 8*k)[0] for k in range((p.oImports - p.oHashes)//8)]
        p.byhash = {}
        for e in p.exports:
            ph, = struct.unpack_from("<Q", p.b, p.oExports + 72*e["i"] + 56)
            p.byhash[ph] = e
    _pk[pkgname] = p
    return p

def resolve(pkg, v):
    """FPackageObjectIndex -> (kind, package, name)"""
    t = v >> 62
    if t == 3: return ("null", None, None)
    if t == 0: return ("export", pkg.name, pkg.exports[v & ((1 << 62) - 1)]["name"])
    if t == 1: return ("script", None, H.get(v, f"?{v:#x}"))
    pi, hi = (v >> 32) & 0x3fffffff, v & 0xffffffff
    pn = pkg.pkgnames[pi] if pi < len(pkg.pkgnames) else f"?pkg{pi}"
    other = load(pn)
    if other and hi < len(pkg.pubhashes) and pkg.pubhashes[hi] in other.byhash:
        return ("pkg", pn, other.byhash[pkg.pubhashes[hi]]["name"])
    return ("pkg", pn, "?")

def callname(pkg, tgt):
    if isinstance(tgt, tuple):
        k, pn, n = resolve(pkg, tgt[1])
        return f"{pn.split('/')[-1]}:{n}" if k == "pkg" else n
    return tgt

def stub_entry(pkg, e):
    """Event stub = LocalFinal ExecuteUbergraph(IntConst entry). Returns entry offset or None."""
    res = kismet.disassemble(pkg, e)
    if not res: return None, None
    r, st = res
    d = r.d
    if d[0] == 0x46 and d[5] == 0x1D:
        return struct.unpack_from("<i", d, 6)[0], r
    return None, r

def flow(pkg, ub, entry):
    """Walk the ubergraph from an entry. Returns (calls on every path?, set of calls seen, exits)."""
    r, st = ub
    idx = {at: i for i, (at, t) in enumerate(st)}
    calls_at = {}
    for at, kind, tgt in r.calls: calls_at.setdefault(at, []).append(callname(pkg, tgt))
    starts = [at for at, t in st]
    def stmt_calls(i):
        lo = st[i][0]; hi = st[i+1][0] if i + 1 < len(st) else 1 << 30
        out = []
        for a, cs in calls_at.items():
            if lo <= a < hi: out += cs
        return out
    # jump targets for a statement: re-read operands from the bytes
    def operand_u32(i):
        # find disk position of statement i by reparsing: simpler to store during disassembly
        return r.jt.get(st[i][0])
    paths = []  # list of call sets per exit path
    seen = set()
    stack = [(idx.get(entry), (), frozenset())]
    steps = 0
    while stack and steps < 20000:
        steps += 1
        i, fs, cs = stack.pop()
        if i is None: continue
        key = (i, fs, cs)
        if key in seen: continue
        seen.add(key)
        at, t = st[i]
        cs = cs | frozenset(stmt_calls(i))
        nxt = i + 1
        if t == 0x06: stack.append((idx.get(r.jt[at]), fs, cs))
        elif t == 0x07: stack.append((idx.get(r.jt[at]), fs, cs)); stack.append((nxt, fs, cs))
        elif t == 0x4C: stack.append((nxt, fs + (r.jt[at],), cs))
        elif t in (0x4D, 0x4F):
            if t == 0x4F: stack.append((nxt, fs, cs))
            if fs: stack.append((idx.get(fs[-1]), fs[:-1], cs))
            else: paths.append(cs)
        elif t in (0x04, 0x53, 0x4E): paths.append(cs)
        else: stack.append((nxt, fs, cs))
    return paths

# Record jump operands during disassembly
_orig_expr = kismet.Reader.expr
def _expr(self):
    at = self.m; t = self.d[self.o]
    if not hasattr(self, "jt"): self.jt = {}
    if t in (0x06, 0x07, 0x4C):
        self.jt[at] = struct.unpack_from("<I", self.d, self.o + 1)[0]
    return _orig_expr(self)
kismet.Reader.expr = _expr

PRES = ("BeginPresentation", "StopPresentation", "IsLongRunning", "IsPresentationFinished")
_cls = {}
def class_info(pkgname):
    """Presentation-related overrides of the Blueprint class in a package, plus its parent."""
    if pkgname in _cls: return _cls[pkgname]
    pkg = load(pkgname)
    info = {"pkg": pkgname, "parent": None, "over": {}, "refresh": False}
    _cls[pkgname] = info
    if not pkg: return info
    cls = [e for e in pkg.exports if e["name"].endswith("_C") and (e["outer"] >> 62) == 3 and not e["name"].startswith("Default__")]
    if not cls: return info
    c = cls[0]
    k, pn, n = resolve(pkg, c["sup"])
    info["parent"] = (k, pn, n)
    ub_e = [e for e in pkg.exports if e["name"].startswith("ExecuteUbergraph_")]
    ub = kismet.disassemble(pkg, ub_e[0]) if ub_e else None
    for e in pkg.exports:
        if e["name"] in PRES:
            entry, r = stub_entry(pkg, e)
            if entry is not None and ub:
                paths = flow(pkg, ub, entry)
            else:
                rr = kismet.disassemble(pkg, e)
                paths = flow(pkg, rr, 0) if rr else []
            info["over"][e["name"]] = paths
    # any RefreshStartTime call anywhere
    for e in pkg.exports:
        if e["oflags"] is not None and e["name"] not in ("Default__",):
            try:
                rr = kismet.disassemble(pkg, e)
            except Exception:
                continue
            if rr and any("RefreshStartTime" in callname(pkg, t) for _, _, t in rr[0].calls):
                info["refresh"] = True
    return info

def chain(pkgname):
    out = []
    while pkgname:
        ci = class_info(pkgname); out.append(ci)
        par = ci["parent"]
        if par and par[0] == "pkg": pkgname = par[1]
        else:
            if par: out.append({"pkg": "native:" + str(par[2]), "over": {}, "parent": None, "refresh": False})
            break
    return out

def fires(ch, i, fn):
    """Does calling fn on class level i end up running the native implementation?
    Returns 'always', 'sometimes' or 'never'."""
    if i >= len(ch) or ch[i]["pkg"].startswith("native:"): return "always"
    paths = ch[i]["over"].get(fn)
    if paths is None: return fires(ch, i + 1, fn)
    if not paths: return "never"
    parent_name = fn
    hits = [any(c.endswith(":" + parent_name) for c in p) for p in paths]
    below = fires(ch, i + 1, fn)
    if not any(hits) or below == "never": return "never"
    if all(hits) and below == "always": return "always"
    return "sometimes"

if __name__ == "__main__":
    ga = sorted(set(p for p in INDEX if re.search(r"/GA_[^/]*\.uasset$", p)))
    rows = []
    for f in ga:
        name = "/Game/" + f[len("../../../SWZeroCompany/Content/"):-len(".uasset")]
        try:
            ch = chain(name)
        except Exception as x:
            rows.append(dict(ability=name, error=str(x))); continue
        begin = fires(ch, 0, "BeginPresentation"); stop = fires(ch, 0, "StopPresentation")
        lr = any("IsLongRunning" in c["over"] for c in ch)
        rf = any(c["refresh"] for c in ch)
        rows.append(dict(ability=name, begin=begin, stop=stop, longrunning=lr, refresh=rf,
                         chain=[c["pkg"].split("/")[-1] for c in ch]))
    json.dump(rows, open("scan.json", "w"), indent=1)
    risky = [r for r in rows if r.get("begin") in ("always", "sometimes") and r.get("stop") != "always"]
    print(len(rows), "abilities scanned;", sum(1 for r in rows if "error" in r), "errors")
    print("RISKY (start event can fire, finish event can be skipped):", len(risky))
    for r in risky: print(f"  {r['ability'].split('/')[-1]:45s} begin={r['begin']:9s} stop={r['stop']:9s} chain={' > '.join(r['chain'])}")
