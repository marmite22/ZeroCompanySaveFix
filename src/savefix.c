// Star Wars Zero Company - save fix (version.dll proxy).
//
// The game blocks saving while an ability's animation ("presentation") is
// playing: FAbilityVisualizationBlocker holds the ability from the native
// BeginPresentation until the native StopPresentation, and every save (manual
// and queued autosaves) is refused meanwhile. The concussion grenade's
// Blueprint overrides StopPresentation with an empty event, so the native one
// never runs and the ability stays held for as long as it exists. Fathom's
// long-running abilities (GA_EldritchEcho, GA_TheCall) hold it for turns.
//
// This DLL notes when each ability's presentation starts. When the game asks
// whether saves are blocked, any ability that has been "presenting" for longer
// than StuckAbilityTimeoutSeconds is released by calling the game's own
// "presentation ended" handler, which is what the native StopPresentation does.
//
// It also logs every save blocker that starts or stops blocking, with the
// game's own reason text, to SWZeroCompanyFix.log.
//
// Everything happens in memory; no game file is changed. Each patch site is
// checked byte for byte before it is touched; on any mismatch that patch stays
// off and the log says so.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "offsets.h"

#define FIX_VERSION "1.0.0"

// ---------------------------------------------------------------------------
// version.dll forwarding
// ---------------------------------------------------------------------------
#define VERSION_EXPORTS(X) \
  X(GetFileVersionInfoA) X(GetFileVersionInfoByHandle) X(GetFileVersionInfoExA) \
  X(GetFileVersionInfoExW) X(GetFileVersionInfoSizeA) X(GetFileVersionInfoSizeExA) \
  X(GetFileVersionInfoSizeExW) X(GetFileVersionInfoSizeW) X(GetFileVersionInfoW) \
  X(VerFindFileA) X(VerFindFileW) X(VerInstallFileA) X(VerInstallFileW) \
  X(VerLanguageNameA) X(VerLanguageNameW) X(VerQueryValueA) X(VerQueryValueW)

#define DECL_PTR(n) void* p_##n;
VERSION_EXPORTS(DECL_PTR)

// Each export is a single indirect jump to the real function, so arguments
// pass through untouched whatever the signature.
#define DECL_STUB(n) __asm__(".globl " #n "\n" #n ":\n  jmp *p_" #n "(%rip)\n");
VERSION_EXPORTS(DECL_STUB)

static void LoadRealVersionDll(void) {
  wchar_t path[MAX_PATH];
  UINT n = GetSystemDirectoryW(path, MAX_PATH);
  if (n == 0 || n > MAX_PATH - 20) return;
  wcscat(path, L"\\version.dll");
  HMODULE real = LoadLibraryW(path);
  if (!real) return;
#define RESOLVE(n) p_##n = (void*)GetProcAddress(real, #n);
  VERSION_EXPORTS(RESOLVE)
}

// ---------------------------------------------------------------------------
// Settings and log
// ---------------------------------------------------------------------------
static wchar_t g_dir[MAX_PATH];
static HANDLE g_log = INVALID_HANDLE_VALUE;
static CRITICAL_SECTION g_logLock;
static int g_cfgLog = 1;
static int g_cfgFix = 1;
static int g_cfgTimeoutMs = 30000;
static int g_cfgLogBlockers = 1;

static void Log(const char* fmt, ...) {
  if (g_log == INVALID_HANDLE_VALUE) return;
  char buf[2048];
  SYSTEMTIME t; GetLocalTime(&t);
  int n = snprintf(buf, sizeof buf, "[%02d:%02d:%02d.%03d] ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
  va_list ap; va_start(ap, fmt);
  int m = vsnprintf(buf + n, sizeof buf - n - 2, fmt, ap);
  va_end(ap);
  if (m < 0) m = 0;
  n += m; if (n > (int)sizeof buf - 2) n = sizeof buf - 2;
  buf[n++] = '\r'; buf[n++] = '\n';
  EnterCriticalSection(&g_logLock);
  DWORD w; WriteFile(g_log, buf, n, &w, NULL);
  LeaveCriticalSection(&g_logLock);
}

static void ReadSettings(HMODULE self) {
  GetModuleFileNameW(self, g_dir, MAX_PATH);
  wchar_t* slash = wcsrchr(g_dir, L'\\');
  if (slash) slash[1] = 0;
  wchar_t ini[MAX_PATH]; _snwprintf(ini, MAX_PATH, L"%lsSWZeroCompanyFix.ini", g_dir);
  g_cfgLog = GetPrivateProfileIntW(L"General", L"LogFile", 1, ini);
  g_cfgFix = GetPrivateProfileIntW(L"Fixes", L"StuckAbilitySaveFix", 1, ini);
  int secs = GetPrivateProfileIntW(L"Fixes", L"StuckAbilityTimeoutSeconds", 30, ini);
  if (secs < 5) secs = 5;
  if (secs > 3600) secs = 3600;
  g_cfgTimeoutMs = secs * 1000;
  g_cfgLogBlockers = GetPrivateProfileIntW(L"Fixes", L"LogSaveBlockers", 1, ini);
}

static void OpenLog(void) {
  InitializeCriticalSection(&g_logLock);
  if (!g_cfgLog) return;
  wchar_t path[MAX_PATH], old[MAX_PATH];
  _snwprintf(path, MAX_PATH, L"%lsSWZeroCompanyFix.log", g_dir);
  _snwprintf(old, MAX_PATH, L"%lsSWZeroCompanyFix.previous.log", g_dir);
  MoveFileExW(path, old, MOVEFILE_REPLACE_EXISTING);
  g_log = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
}

// ---------------------------------------------------------------------------
// Game memory helpers
// ---------------------------------------------------------------------------
static uint8_t* g_base;
static uint32_t g_imageSize;
static uint8_t* g_text; static uint32_t g_textSize;

static int MatchAt(const uint8_t* p, const Sig* s) {
  for (uint32_t i = 0; i < s->len; i++)
    if (s->mask[i] && p[i] != s->bytes[i]) return 0;
  return 1;
}

// Returns the address of a signature: at its expected place, else the single
// match in .text, else NULL.
static uint8_t* FindSig(const Sig* s) {
  if (s->rva + s->len <= g_imageSize && MatchAt(g_base + s->rva, s)) return g_base + s->rva;
  uint8_t* hit = NULL; int count = 0;
  uint32_t first = 0; while (first < s->len && !s->mask[first]) first++;
  for (uint32_t i = 0; i + s->len <= g_textSize; i++) {
    if (g_text[i + first] != s->bytes[first]) continue;
    if (MatchAt(g_text + i, s)) { hit = g_text + i; if (++count > 1) return NULL; }
  }
  if (hit) Log("  %s found at a different address (+%#llx), game build differs", s->name, (unsigned long long)(hit - g_base));
  return hit;
}

static int WriteMem(void* dst, const void* src, size_t n) {
  DWORD old;
  if (!VirtualProtect(dst, n, PAGE_EXECUTE_READWRITE, &old)) return 0;
  memcpy(dst, src, n);
  VirtualProtect(dst, n, old, &old);
  FlushInstructionCache(GetCurrentProcess(), dst, n);
  return 1;
}

// Executable memory within +-2 GB of the game, for a jump stub.
static uint8_t* AllocNear(uint8_t* target) {
  SYSTEM_INFO si; GetSystemInfo(&si);
  uintptr_t gran = si.dwAllocationGranularity;
  uintptr_t lo = (uintptr_t)target > 0x70000000 ? (uintptr_t)target - 0x70000000 : gran;
  uintptr_t hi = (uintptr_t)target + 0x70000000;
  for (uintptr_t a = ((uintptr_t)target & ~(gran - 1)); a > lo; a -= gran) {
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery((void*)a, &mbi, sizeof mbi)) break;
    if (mbi.State == MEM_FREE) {
      void* p = VirtualAlloc((void*)a, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
      if (p) return p;
    }
  }
  for (uintptr_t a = ((uintptr_t)target & ~(gran - 1)) + gran; a < hi; a += gran) {
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery((void*)a, &mbi, sizeof mbi)) break;
    if (mbi.State == MEM_FREE) {
      void* p = VirtualAlloc((void*)a, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
      if (p) return p;
    }
  }
  return NULL;
}

// --- UObject access (UE 5.6 layout, checked against the game's own code) ---
// FUObjectArray: +0x10 chunk table (FUObjectItem**), +0x24 element count.
// FUObjectItem (24 bytes): +0 Object, +8 Flags, +0x10 SerialNumber.
// UObjectBase: +0xC InternalIndex.
static uint8_t* g_GUObjectArray;
static void*** g_GMalloc;

typedef struct { void* object; int32_t flags; int32_t cluster; int32_t serial; int32_t pad; } FUObjectItem;
#define RF_GARBAGE_OR_UNREACHABLE 0x10200000

static FUObjectItem* ItemForIndex(int32_t index) {
  if (index < 0 || index >= *(int32_t*)(g_GUObjectArray + 0x24)) return NULL;
  FUObjectItem** chunks = *(FUObjectItem***)(g_GUObjectArray + 0x10);
  FUObjectItem* chunk = chunks[(uint32_t)index >> 16];
  return chunk ? &chunk[index & 0xFFFF] : NULL;
}

// Resolves a TWeakObjectPtr (index, serial) the way the game does.
static void* ResolveWeak(uint64_t weak) {
  int32_t index = (int32_t)(weak & 0xFFFFFFFF), serial = (int32_t)(weak >> 32);
  if (serial == 0) return NULL;
  FUObjectItem* it = ItemForIndex(index);
  if (!it || it->serial != serial || (it->flags & RF_GARBAGE_OR_UNREACHABLE)) return NULL;
  return it->object;
}

static uint64_t WeakKeyFor(void* obj) {
  int32_t index = *(int32_t*)((uint8_t*)obj + 0xC);
  FUObjectItem* it = ItemForIndex(index);
  if (!it || it->object != obj || it->serial == 0) return 0;
  return (uint32_t)index | ((uint64_t)(uint32_t)it->serial << 32);
}

// FString = { wchar_t* data; int32 num; int32 max; }
typedef struct { wchar_t* data; int32_t num; int32_t max; } FString;

static void FreeFString(FString* s) {
  if (!s->data) return;
  void** gm = g_GMalloc ? *g_GMalloc : NULL;
  if (gm) ((void (*)(void*, void*))((void**)*gm)[0x48 / 8])(gm, s->data);
  s->data = NULL;
}

static void LogFString(const char* prefix, FString* s) {
  char utf8[1024] = "";
  if (s->data && s->num > 0)
    WideCharToMultiByte(CP_UTF8, 0, s->data, -1, utf8, sizeof utf8 - 1, NULL, NULL);
  Log("%s%s", prefix, utf8);
}

// ---------------------------------------------------------------------------
// Fix: release abilities stuck in FAbilityVisualizationBlocker
// ---------------------------------------------------------------------------
typedef void (*OnPresented_t)(void* handler, void* ability);
typedef void (*OnEnded_t)(void* handler, void* ability);
typedef char (*IsBlocked_t)(void* blocker);
typedef FString* (*GetReason_t)(void* blocker, FString* out);

static OnPresented_t g_OnPresented;
static OnEnded_t g_OnEnded;
static IsBlocked_t g_AvbIsBlocked;
static GetReason_t g_AvbGetReason;

// When each ability (by weak key) started presenting.
#define MAX_STAMPS 512
typedef struct { uint64_t key; uint64_t since; } Stamp;
static Stamp g_stamps[MAX_STAMPS];
static int g_numStamps;
static uint64_t g_released;
static uint64_t (*g_now)(void) = GetTickCount64;  // replaced by the logic test

static Stamp* FindStamp(uint64_t key) {
  for (int i = 0; i < g_numStamps; i++) if (g_stamps[i].key == key) return &g_stamps[i];
  return NULL;
}

static void SetStamp(uint64_t key, uint64_t now) {
  Stamp* s = FindStamp(key);
  if (s) { s->since = now; return; }
  if (g_numStamps == MAX_STAMPS) {
    // Drop the oldest. An entry this old is long gone or long stuck; either way
    // it is re-stamped on the next blocked check.
    int oldest = 0;
    for (int i = 1; i < g_numStamps; i++) if (g_stamps[i].since < g_stamps[oldest].since) oldest = i;
    g_stamps[oldest] = g_stamps[--g_numStamps];
  }
  g_stamps[g_numStamps].key = key; g_stamps[g_numStamps].since = now; g_numStamps++;
}

// Called from the patched call in UTSB_AbilityEventHandler::execOnAbilityPresented.
static void Hook_OnAbilityPresented(void* handler, void* ability) {
  g_OnPresented(handler, ability);
  if (!ability) return;
  uint64_t key = WeakKeyFor(ability);
  if (key) SetStamp(key, g_now());
}

// Walk the blocker's TSet<TWeakObjectPtr<UBitReactorGameplayAbility>> at +0x20.
// TSparseArray: +0x20 data (16-byte elements, weak ptr first), +0x28 count;
// allocation bits: inline +0x30, heap +0x40, bit count +0x48.
typedef void (*EntryFn)(uint64_t key, void* ctx);
static void ForEachEntry(uint8_t* blocker, EntryFn fn, void* ctx) {
  uint8_t* data = *(uint8_t**)(blocker + 0x20);
  int32_t num = *(int32_t*)(blocker + 0x28);
  uint32_t* bits = *(uint32_t**)(blocker + 0x40);
  if (!bits) bits = (uint32_t*)(blocker + 0x30);
  int32_t numBits = *(int32_t*)(blocker + 0x48);
  if (!data || num <= 0) return;
  if (num > numBits) num = numBits;
  for (int32_t i = 0; i < num; i++)
    if (bits[i >> 5] & (1u << (i & 31))) fn(*(uint64_t*)(data + (size_t)i * 16), ctx);
}

typedef struct { uint64_t now; void* stale[64]; int numStale; uint64_t live[MAX_STAMPS]; int numLive; uint64_t oldestMs; } Scan;

static void ScanEntry(uint64_t key, void* p) {
  Scan* sc = p;
  if (sc->numLive < MAX_STAMPS) sc->live[sc->numLive++] = key;
  Stamp* st = FindStamp(key);
  if (!st) { SetStamp(key, sc->now); return; }  // not seen being presented: start its clock now
  uint64_t age = sc->now - st->since;
  if (age > sc->oldestMs) sc->oldestMs = age;
  if (age >= (uint64_t)g_cfgTimeoutMs && sc->numStale < 64) {
    void* obj = ResolveWeak(key);
    if (obj) sc->stale[sc->numStale++] = obj;  // dead entries the game removes itself
  }
}

static char Fix_AvbIsBlocked(void* blocker) {
  if (g_cfgFix && g_OnEnded) {
    static Scan sc;
    memset(&sc, 0, sizeof sc);
    sc.now = g_now();
    ForEachEntry(blocker, ScanEntry, &sc);
    // Forget stamps for abilities that are no longer in the set.
    for (int i = 0; i < g_numStamps;) {
      int found = 0;
      for (int j = 0; j < sc.numLive; j++) if (sc.live[j] == g_stamps[i].key) { found = 1; break; }
      if (!found && sc.now - g_stamps[i].since > 60000) g_stamps[i] = g_stamps[--g_numStamps];
      else i++;
    }
    if (sc.numStale) {
      if (g_AvbGetReason) {
        FString r = {0};
        g_AvbGetReason(blocker, &r);
        LogFString("[savefix] saves were blocked: ", &r);
        FreeFString(&r);
      }
      // The game's handler only reads the blocker pointer at +0x28 of its
      // handler object, so a small stand-in is enough.
      uint8_t fakeHandler[0x40] = {0};
      *(void**)(fakeHandler + 0x28) = blocker;
      for (int i = 0; i < sc.numStale; i++) {
        uint64_t key = WeakKeyFor(sc.stale[i]);
        Stamp* st = FindStamp(key);
        Log("[savefix] ability %p has been presenting for %llu s without finishing; releasing it so the game can save",
            sc.stale[i], st ? (unsigned long long)((sc.now - st->since) / 1000) : 0ULL);
        g_OnEnded(fakeHandler, sc.stale[i]);
        g_released++;
      }
      Log("[savefix] released %d stuck ability(s) (total this session: %llu)", sc.numStale, (unsigned long long)g_released);
    }
  }
  return g_AvbIsBlocked(blocker);
}

// ---------------------------------------------------------------------------
// Diagnostics: log when any save blocker starts or stops blocking
// ---------------------------------------------------------------------------
static IsBlocked_t g_vtOrig[BLOCKER_VT_COUNT];
static GetReason_t g_vtReason[BLOCKER_VT_COUNT];
static int g_vtLast[BLOCKER_VT_COUNT];
static int g_inDiag;

static char Diag(int i, void* self) {
  char r = (i == 0) ? Fix_AvbIsBlocked(self) : g_vtOrig[i](self);
  int b = r != 0;
  if (g_cfgLogBlockers && b != g_vtLast[i] && !g_inDiag) {
    g_vtLast[i] = b;
    if (b && g_vtReason[i]) {
      g_inDiag = 1;
      FString s = {0};
      g_vtReason[i](self, &s);
      char prefix[128]; snprintf(prefix, sizeof prefix, "[blocker] %s is blocking saves: ", g_blockerVts[i].name);
      LogFString(prefix, &s);
      FreeFString(&s);
      g_inDiag = 0;
    } else {
      Log("[blocker] %s %s", g_blockerVts[i].name, b ? "is blocking saves" : "no longer blocks saves");
    }
  }
  return r;
}

#define DIAG_FN(i) static char Diag##i(void* self) { return Diag(i, self); }
DIAG_FN(0) DIAG_FN(1) DIAG_FN(2) DIAG_FN(3) DIAG_FN(4) DIAG_FN(5) DIAG_FN(6) DIAG_FN(7)
static IsBlocked_t g_diagFns[BLOCKER_VT_COUNT] = { Diag0, Diag1, Diag2, Diag3, Diag4, Diag5, Diag6, Diag7 };

// ---------------------------------------------------------------------------
// Install
// ---------------------------------------------------------------------------
static int32_t Rel32(uint8_t* insn, int dispOffset, int insnLen) {
  (void)insnLen; return *(int32_t*)(insn + dispOffset);
}

// Reads a rip-relative operand target from an instruction found in a function.
static uint8_t* RipTarget(uint8_t* insn, int dispOffset, int insnLen) {
  return insn + insnLen + Rel32(insn, dispOffset, insnLen);
}

static uint8_t* FindBytes(uint8_t* from, size_t range, const uint8_t* pat, size_t n) {
  for (size_t i = 0; i + n <= range; i++) if (!memcmp(from + i, pat, n)) return from + i;
  return NULL;
}

static void Install(void) {
  g_base = (uint8_t*)GetModuleHandleW(NULL);
  IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)g_base;
  IMAGE_NT_HEADERS64* nt = (IMAGE_NT_HEADERS64*)(g_base + dos->e_lfanew);
  g_imageSize = nt->OptionalHeader.SizeOfImage;
  IMAGE_SECTION_HEADER* sec = IMAGE_FIRST_SECTION(nt);
  for (int i = 0; i < nt->FileHeader.NumberOfSections; i++)
    if (!memcmp(sec[i].Name, ".text", 6)) { g_text = g_base + sec[i].VirtualAddress; g_textSize = sec[i].Misc.VirtualSize; }

  wchar_t exe[MAX_PATH]; GetModuleFileNameW(NULL, exe, MAX_PATH);
  char exe8[MAX_PATH * 3]; WideCharToMultiByte(CP_UTF8, 0, exe, -1, exe8, sizeof exe8, NULL, NULL);
  Log("SWZeroCompanyFix %s loaded into %s", FIX_VERSION, exe8);
  Log("settings: StuckAbilitySaveFix=%d StuckAbilityTimeoutSeconds=%d LogSaveBlockers=%d", g_cfgFix, g_cfgTimeoutMs / 1000, g_cfgLogBlockers);
  if (!g_text || !wcsstr(exe, L"SWZeroCompany")) { Log("not the game executable; doing nothing"); return; }
  if (nt->FileHeader.TimeDateStamp != EXPECT_TIMESTAMP || g_imageSize != EXPECT_SIZEOFIMAGE)
    Log("note: game build differs from the one this fix was made for (199049); searching for each patch site");
  else
    Log("game build 199049 (as expected)");

  uint8_t* f[SIG_COUNT];
  for (int i = 0; i < SIG_COUNT; i++) {
    f[i] = FindSig(&g_sigs[i]);
    if (!f[i] && i != SIG_H_execOnPresented) Log("  %s: not found", g_sigs[i].name);
  }

  // Globals, read from the game's own instructions.
  // AVB_IsBlocked: "cmp eax, [rip+X]" (3B 05) where X = GUObjectArray+0x24.
  if (f[SIG_AVB_IsBlocked]) {
    static const uint8_t cmpEax[] = {0x3B, 0x05};
    uint8_t* p = FindBytes(f[SIG_AVB_IsBlocked], 0x100, cmpEax, 2);
    if (p) g_GUObjectArray = RipTarget(p, 2, 6) - 0x24;
  }
  // FilterAbility: "mov rcx, [rip+X]" (48 8B 0D) where X = GMalloc.
  if (f[SIG_AVB_FilterAbility]) {
    static const uint8_t movRcx[] = {0x48, 0x8B, 0x0D};
    uint8_t* p = FindBytes(f[SIG_AVB_FilterAbility], 0x90, movRcx, 3);
    if (p) g_GMalloc = (void***)RipTarget(p, 3, 7);
  }
  if (g_GUObjectArray != g_base + RVA_GUObjectArray || (void*)g_GMalloc != (void*)(g_base + RVA_UE__Private__GMalloc))
    Log("note: object table/allocator found at a different place than in build 199049");
  if (!g_GUObjectArray || !g_GMalloc) { Log("could not find the game's object table; doing nothing"); return; }

  g_OnPresented = (OnPresented_t)f[SIG_H_OnPresented];
  g_OnEnded = (OnEnded_t)f[SIG_H_OnEnded];
  g_AvbIsBlocked = (IsBlocked_t)f[SIG_AVB_IsBlocked];
  g_AvbGetReason = (GetReason_t)f[SIG_AVB_GetReason];

  // 1. Patch the call in execOnAbilityPresented so we see each presentation start.
  int presentHooked = 0;
  if (g_OnPresented) {
    uint8_t* call = NULL;
    if (f[SIG_H_execOnPresented]) {
      uint8_t* c = f[SIG_H_execOnPresented] + CALLSITE_execOnPresented_off;
      if (c[0] == 0xE8 && c + 5 + *(int32_t*)(c + 1) == (uint8_t*)g_OnPresented) call = c;
    }
    if (!call) {  // find the one direct call to OnAbilityPresented
      int n = 0;
      for (uint32_t i = 0; i + 5 <= g_textSize; i++)
        if (g_text[i] == 0xE8 && g_text + i + 5 + *(int32_t*)(g_text + i + 1) == (uint8_t*)g_OnPresented) { call = g_text + i; n++; }
      if (n != 1) call = NULL;
    }
    uint8_t* stub = call ? AllocNear(call) : NULL;
    if (stub) {
      // jmp qword ptr [rip+0]; dq Hook_OnAbilityPresented
      uint8_t s[14] = {0xFF, 0x25, 0, 0, 0, 0};
      void* h = (void*)Hook_OnAbilityPresented; memcpy(s + 6, &h, 8);
      memcpy(stub, s, sizeof s);
      DWORD old; VirtualProtect(stub, 4096, PAGE_EXECUTE_READ, &old);
      int32_t rel = (int32_t)(stub - (call + 5));
      if (WriteMem(call + 1, &rel, 4)) presentHooked = 1;
    }
  }
  Log("ability presentation tracking: %s", presentHooked ? "on" : "OFF (stuck abilities are timed from the first blocked save check instead)");

  // 2. Swap IsBlocked in each save blocker's vtable.
  int fixOn = 0;
  for (int i = 0; i < BLOCKER_VT_COUNT; i++) {
    const BlockerVt* b = &g_blockerVts[i];
    void** vt = (void**)(g_base + b->vtable);
    int ok = (b->vtable + 0x28 <= g_imageSize) && vt[3] == (void*)(g_base + b->isBlocked) && vt[4] == (void*)(g_base + b->getReason);
    if (i == 0) ok = ok && g_AvbIsBlocked == (IsBlocked_t)vt[3];
    if (!ok) { Log("  %s: vtable not as expected; left alone", b->name); continue; }
    g_vtOrig[i] = (IsBlocked_t)vt[3];
    g_vtReason[i] = (GetReason_t)vt[4];
    if (i == 0 && !(g_OnEnded && g_AvbGetReason)) { Log("  %s: handler not found; fix off", b->name); continue; }
    if (i != 0 && !g_cfgLogBlockers) continue;
    void* fn = (void*)g_diagFns[i];
    if (WriteMem(&vt[3], &fn, sizeof fn)) { if (i == 0) fixOn = 1; }
  }
  Log("stuck ability save fix: %s", fixOn && g_cfgFix ? "ON" : "OFF");
  Log("save blocker logging: %s", g_cfgLogBlockers ? "ON" : "OFF");
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved) {
  (void)reserved;
  if (reason == DLL_PROCESS_ATTACH) {
    DisableThreadLibraryCalls(inst);
    LoadRealVersionDll();
    ReadSettings(inst);
    OpenLog();
    Install();
  }
  return TRUE;
}
