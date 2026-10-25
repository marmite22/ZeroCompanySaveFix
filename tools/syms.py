"""Query SWZeroCompany.pdb via dbghelp. Usage: syms.py <mask> [<mask>...]  (mask like *SaveGame*)
Prints RVA, size, name. Use 'addr:0x1234' to look up the symbol at an RVA."""
import ctypes, sys
from ctypes import wintypes as W

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Star Wars Zero Company\SWZeroCompany\Binaries\Win64\SWZeroCompany.exe"
BASE = 0x140000000

dbg = ctypes.WinDLL("dbghelp.dll")

class SYMBOL_INFO(ctypes.Structure):
    _fields_ = [("SizeOfStruct", W.ULONG), ("TypeIndex", W.ULONG), ("Reserved", ctypes.c_uint64 * 2),
                ("Index", W.ULONG), ("Size", W.ULONG), ("ModBase", ctypes.c_uint64), ("Flags", W.ULONG),
                ("Value", ctypes.c_uint64), ("Address", ctypes.c_uint64), ("Register", W.ULONG),
                ("Scope", W.ULONG), ("Tag", W.ULONG), ("NameLen", W.ULONG), ("MaxNameLen", W.ULONG),
                ("Name", ctypes.c_char * 2000)]

CB = ctypes.WINFUNCTYPE(W.BOOL, ctypes.POINTER(SYMBOL_INFO), W.ULONG, ctypes.c_void_p)
hp = W.HANDLE(0x1234)
dbg.SymSetOptions(0x2 | 0x4 | 0x10)  # UNDNAME | DEFERRED_LOADS | LOAD_LINES
dbg.SymInitialize.argtypes = [W.HANDLE, ctypes.c_char_p, W.BOOL]
dbg.SymInitialize(hp, None, False)
dbg.SymLoadModuleEx.restype = ctypes.c_uint64
dbg.SymLoadModuleEx.argtypes = [W.HANDLE, W.HANDLE, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint64, W.DWORD, ctypes.c_void_p, W.DWORD]
base = dbg.SymLoadModuleEx(hp, None, GAME.encode(), None, BASE, 0, None, 0)
assert base, ctypes.GetLastError()

def enum(mask):
    out = []
    @CB
    def cb(p, size, ctx):
        s = p.contents
        out.append((s.Address - BASE, s.Size, s.Tag, s.Name[:s.NameLen].decode(errors="replace")))
        return True
    dbg.SymEnumSymbols.argtypes = [W.HANDLE, ctypes.c_uint64, ctypes.c_char_p, CB, ctypes.c_void_p]
    dbg.SymEnumSymbols(hp, base, mask.encode(), cb, None)
    return out

def at(rva):
    s = SYMBOL_INFO(); s.SizeOfStruct = 88; s.MaxNameLen = 2000
    disp = ctypes.c_uint64()
    dbg.SymFromAddr.argtypes = [W.HANDLE, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(SYMBOL_INFO)]
    if dbg.SymFromAddr(hp, BASE + rva, ctypes.byref(disp), ctypes.byref(s)):
        return s.Name[:s.NameLen].decode(errors="replace"), disp.value, s.Address - BASE, s.Size
    return None

if __name__ == "__main__":
    for a in sys.argv[1:]:
        if a.startswith("addr:"):
            print(at(int(a[5:], 16)))
            continue
        for rva, size, tag, name in sorted(enum(a), key=lambda x: x[3]):
            print(f"{rva:#010x} {size:6d} {tag:3d} {name}")
