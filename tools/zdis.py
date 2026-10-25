"""Disassemble SWZeroCompany.exe with symbol annotation.
Usage: dis.py <rva-hex | exact symbol name> [nbytes=0x300]
Stops at first int3 padding after a ret unless nbytes given explicitly with '!' suffix."""
import bisect, sys, re, struct, pefile, capstone, os
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Star Wars Zero Company\SWZeroCompany\Binaries\Win64\SWZeroCompany.exe"
BASE = 0x140000000

_addrs, _names, _byname = [], [], {}
def load():
    if _addrs: return
    with open(os.path.join(HERE, "allsyms.tsv"), encoding="utf-8") as f:
        for line in f:
            a, s, t, n = line.rstrip("\n").split("\t", 3)
            a = int(a, 16)
            _addrs.append(a); _names.append(n)
            _byname.setdefault(n, a)

def name_at(rva):
    load()
    i = bisect.bisect_right(_addrs, rva) - 1
    if i < 0: return None
    # prefer exact
    off = rva - _addrs[i]
    if off > 0x100000: return None
    return _names[i] + (f"+{off:#x}" if off else "")

def find(name):
    load(); return _byname.get(name)

_pe = None; _data = None
def pe():
    global _pe, _data
    if _pe is None:
        _pe = pefile.PE(GAME, fast_load=True)
        _data = open(GAME, "rb").read()
    return _pe

def read(rva, n):
    p = pe()
    for s in p.sections:
        if s.VirtualAddress <= rva < s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData):
            off = s.PointerToRawData + (rva - s.VirtualAddress)
            return _data[off:off + n]
    return b""

def u64(rva): return struct.unpack("<Q", read(rva, 8))[0]

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail = False

def dis(rva, n=0x300, stop=True, out=print):
    code = read(rva, n)
    last_ret = False
    for ins in md.disasm(code, BASE + rva):
        r = ins.address - BASE
        ann = ""
        m = re.search(r"0x([0-9a-f]{9,})", ins.op_str)
        if m:
            tgt = int(m.group(1), 16) - BASE
            nm = name_at(tgt)
            if nm: ann = f"   ; {nm}"
        if "rip +" in ins.op_str or "rip -" in ins.op_str:
            m2 = re.search(r"rip ([+-]) (0x[0-9a-f]+)", ins.op_str)
            d = int(m2.group(2), 16) * (1 if m2.group(1) == "+" else -1)
            tgt = r + ins.size + d
            nm = name_at(tgt)
            ann = f"   ; [{tgt:#x}] {nm or ''}"
        out(f"{r:#010x}: {ins.bytes.hex():<24} {ins.mnemonic} {ins.op_str}{ann}")
        if stop and ins.mnemonic == "int3" and last_ret: break
        last_ret = ins.mnemonic in ("ret", "jmp") and not ins.op_str.startswith("0x")
        if stop and ins.mnemonic == "int3": break

if __name__ == "__main__":
    a = sys.argv[1]
    try: rva = int(a, 16)
    except ValueError:
        rva = find(a); assert rva is not None, "not found"
    n = 0x300; stop = True
    if len(sys.argv) > 2:
        x = sys.argv[2]; stop = not x.endswith("!"); n = int(x.rstrip("!"), 16)
    print(f"== {name_at(rva)} @ {rva:#x}")
    dis(rva, n, stop)
