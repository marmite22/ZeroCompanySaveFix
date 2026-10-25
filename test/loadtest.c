// Load test: starts the game under a debugger, stops it at the exe's entry
// point (our version.dll has loaded and patched by then, no game code has run,
// Steam and saves are never touched), checks every patch in the live process,
// then kills it.
// Usage: loadtest.exe "<path to SWZeroCompany\Binaries\Win64\SWZeroCompany.exe>"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include "../src/offsets.h"

static HANDLE hp;
static int Rd(uint64_t a, void* b, size_t n) { SIZE_T r; return ReadProcessMemory(hp, (void*)a, b, n, &r) && r == n; }

int wmain(int argc, wchar_t** argv) {
  if (argc < 2) { printf("usage: loadtest <game exe>\n"); return 2; }
  wchar_t dir[MAX_PATH]; wcscpy(dir, argv[1]); *wcsrchr(dir, L'\\') = 0;
  STARTUPINFOW si = { sizeof si }; PROCESS_INFORMATION pi;
  if (!CreateProcessW(argv[1], NULL, NULL, NULL, FALSE, DEBUG_ONLY_THIS_PROCESS, NULL, dir, &si, &pi)) {
    printf("CreateProcess failed %lu\n", GetLastError()); return 2;
  }
  hp = pi.hProcess;
  uint64_t base = 0, entry = 0, dllBase = 0, dllEnd = 0; uint8_t orig = 0; int fails = 0, done = 0;
  DEBUG_EVENT ev;
  while (!done && WaitForDebugEvent(&ev, 120000)) {
    DWORD cont = DBG_CONTINUE;
    switch (ev.dwDebugEventCode) {
    case CREATE_PROCESS_DEBUG_EVENT: {
      base = (uint64_t)ev.u.CreateProcessInfo.lpBaseOfImage;
      entry = (uint64_t)ev.u.CreateProcessInfo.lpStartAddress;
      uint8_t cc = 0xCC; SIZE_T w;
      Rd(entry, &orig, 1);
      WriteProcessMemory(hp, (void*)entry, &cc, 1, &w);
      FlushInstructionCache(hp, (void*)entry, 1);
      printf("game image at %#llx, entry %#llx\n", (unsigned long long)base, (unsigned long long)entry);
      CloseHandle(ev.u.CreateProcessInfo.hFile);
      break; }
    case LOAD_DLL_DEBUG_EVENT: {
      wchar_t name[MAX_PATH] = L"";
      if (ev.u.LoadDll.hFile) GetFinalPathNameByHandleW(ev.u.LoadDll.hFile, name, MAX_PATH, 0);
      if (wcsstr(name, L"Binaries\\Win64\\version.dll")) {
        dllBase = (uint64_t)ev.u.LoadDll.lpBaseOfDll;
        IMAGE_DOS_HEADER d; IMAGE_NT_HEADERS64 nt;
        Rd(dllBase, &d, sizeof d); Rd(dllBase + d.e_lfanew, &nt, sizeof nt);
        dllEnd = dllBase + nt.OptionalHeader.SizeOfImage;
        printf("fix DLL loaded at %#llx: %ls\n", (unsigned long long)dllBase, name);
      }
      if (ev.u.LoadDll.hFile) CloseHandle(ev.u.LoadDll.hFile);
      break; }
    case EXCEPTION_DEBUG_EVENT: {
      uint64_t at = (uint64_t)ev.u.Exception.ExceptionRecord.ExceptionAddress;
      if (ev.u.Exception.ExceptionRecord.ExceptionCode == EXCEPTION_BREAKPOINT && at == entry) {
        printf("stopped at entry point; checking patches\n");
        if (!dllBase) { printf("FAIL: fix DLL was not loaded from the game folder\n"); fails++; }
        for (int i = 0; i < BLOCKER_VT_COUNT; i++) {
          uint64_t slot; Rd(base + g_blockerVts[i].vtable + 0x18, &slot, 8);
          int ok = slot >= dllBase && slot < dllEnd;
          printf("  %-28s IsBlocked -> %s\n", g_blockerVts[i].name, ok ? "fix DLL (patched)" : "game (NOT patched)");
          if (!ok) fails++;
        }
        uint64_t call = base + g_sigs[SIG_H_execOnPresented].rva + CALLSITE_execOnPresented_off;
        uint8_t c[5]; Rd(call, c, 5);
        uint64_t tgt = call + 5 + *(int32_t*)(c + 1);
        uint8_t stub[14]; Rd(tgt, stub, 14);
        uint64_t hook = *(uint64_t*)(stub + 6);
        int ok = c[0] == 0xE8 && stub[0] == 0xFF && stub[1] == 0x25 && hook >= dllBase && hook < dllEnd;
        printf("  execOnAbilityPresented call -> stub %#llx -> %#llx %s\n", (unsigned long long)tgt, (unsigned long long)hook, ok ? "(fix DLL, patched)" : "(NOT patched)");
        if (!ok) fails++;
        done = 1;
      } else if (ev.u.Exception.dwFirstChance) {
        cont = (ev.u.Exception.ExceptionRecord.ExceptionCode == EXCEPTION_BREAKPOINT) ? DBG_CONTINUE : DBG_EXCEPTION_NOT_HANDLED;
      }
      break; }
    case EXIT_PROCESS_DEBUG_EVENT:
      printf("FAIL: game exited early (code %lu)\n", ev.u.ExitProcess.dwExitCode); fails++; done = 1; break;
    }
    if (!done) ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, cont);
  }
  TerminateProcess(hp, 0);
  DebugActiveProcessStop(pi.dwProcessId);
  printf(fails ? "LOAD TEST FAILED (%d)\n" : "LOAD TEST PASSED\n", fails);
  return fails ? 1 : 0;
}
