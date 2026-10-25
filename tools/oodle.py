"""Use the game's statically linked Oodle decoder: SWZeroCompany.exe is loaded as a library (entry point not run)
and its import table is filled in here, since Windows leaves an EXE's imports unresolved in that case."""
import ctypes, struct
from ctypes import wintypes as W
GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Star Wars Zero Company\SWZeroCompany\Binaries\Win64"
EXE = GAME_DIR + r"\SWZeroCompany.exe"
RVA_Decompress = 0xbc59d20
RVA_MemSize = 0xbc593e0
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.LoadLibraryExW.restype = W.HMODULE; k32.LoadLibraryExW.argtypes = [W.LPCWSTR, W.HANDLE, W.DWORD]
k32.LoadLibraryA.restype = W.HMODULE; k32.LoadLibraryA.argtypes = [ctypes.c_char_p]
k32.GetProcAddress.restype = ctypes.c_void_p; k32.GetProcAddress.argtypes = [W.HMODULE, ctypes.c_char_p]
k32.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, W.DWORD, ctypes.POINTER(W.DWORD)]
k32.SetDllDirectoryW(GAME_DIR)
LOAD_LIBRARY_AS_IMAGE_RESOURCE = 0
base = k32.LoadLibraryExW(EXE, None, 0)
if not base: raise OSError(ctypes.get_last_error())

def rd(addr, n): return ctypes.string_at(addr, n)
def u32(a): return struct.unpack("<I", rd(a, 4))[0]
def u64(a): return struct.unpack("<Q", rd(a, 8))[0]
def cstr(a): return ctypes.string_at(a)

def _fix_imports():
    pe = base + u32(base + 0x3C)
    imp_rva, imp_size = struct.unpack("<II", rd(pe + 24 + 112 + 8, 8))  # DataDirectory[1]
    d = base + imp_rva
    while True:
        oft, _, _, name, ft = struct.unpack("<IIIII", rd(d, 20))
        if not name: break
        dll = cstr(base + name)
        h = k32.LoadLibraryA(dll)
        th = base + (oft or ft); iat = base + ft; i = 0
        old = W.DWORD()
        while True:
            e = u64(th + 8*i)
            if not e: break
            if h:
                key = ctypes.c_char_p(e & 0xFFFF) if e >> 63 else cstr(base + (e & 0x7FFFFFFF) + 2)
                fn = k32.GetProcAddress(h, key) or 0
            else:
                fn = 0
            if fn:
                k32.VirtualProtect(iat + 8*i, 8, 0x04, ctypes.byref(old))
                ctypes.c_uint64.from_address(iat + 8*i).value = fn
                k32.VirtualProtect(iat + 8*i, 8, old.value, ctypes.byref(old))
            i += 1
        d += 20
_fix_imports()

_dec = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_int64,
                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int64,
                        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int)(base + RVA_Decompress)
_msz = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_int, ctypes.c_int64)(base + RVA_MemSize)
_memsize = _msz(-1, -1)
_mem = ctypes.create_string_buffer(max(_memsize, 1))
def decompress(comp: bytes, rawlen: int) -> bytes:
    out = ctypes.create_string_buffer(rawlen)
    n = _dec(comp, len(comp), out, rawlen, 1, 0, 0, None, 0, None, None, _mem, _memsize, 3)
    if n != rawlen: raise ValueError(f"oodle returned {n}, expected {rawlen}")
    return out.raw
