// Logic test for the stuck-ability fix, against a fake game: a fake object
// table, a fake FAbilityVisualizationBlocker set with the game's layout, and
// stand-ins for the game's handlers. Build: see build.sh (test target).
#include "../src/savefix.c"
#undef assert
#define assert(c) do { if (!(c)) { printf("CHECK FAILED line %d: %s\n", __LINE__, #c); fflush(stdout); ExitProcess(1); } } while (0)

static uint64_t t_now;
static uint64_t FakeNow(void) { return t_now; }

// Fake object table: one chunk of 16 items.
static FUObjectItem items[16];
static FUObjectItem* chunkTable[1] = { items };
static uint8_t fakeArray[0x30];
static uint8_t objs[16][0x40];

static void* MakeObj(int idx, int serial) {
  *(int32_t*)(objs[idx] + 0xC) = idx;
  items[idx].object = objs[idx]; items[idx].serial = serial; items[idx].flags = 0;
  return objs[idx];
}

// Fake blocker with the game's TSet layout.
static uint8_t blocker[0x70];
static uint8_t elems[16 * 16];

static void SetAdd(void* obj) {
  uint64_t key = WeakKeyFor(obj);
  int32_t* num = (int32_t*)(blocker + 0x28);
  uint32_t* bits = (uint32_t*)(blocker + 0x30);
  for (int i = 0; i < *num; i++)
    if ((bits[0] & (1u << i)) && *(uint64_t*)(elems + i * 16) == key) return;
  int i = (*num)++;
  *(uint64_t*)(elems + i * 16) = key;
  bits[0] |= 1u << i;
  *(int32_t*)(blocker + 0x48) = *num;
}

static int endedCalls; static void* lastEnded;
static void FakeOnPresented(void* h, void* a) { (void)h; SetAdd(a); }
static void FakeOnEnded(void* h, void* a) {
  assert(*(void**)((uint8_t*)h + 0x28) == blocker);
  endedCalls++; lastEnded = a;
  uint64_t key = WeakKeyFor(a);
  int32_t num = *(int32_t*)(blocker + 0x28);
  uint32_t* bits = (uint32_t*)(blocker + 0x30);
  for (int i = 0; i < num; i++)
    if ((bits[0] & (1u << i)) && *(uint64_t*)(elems + i * 16) == key) bits[0] &= ~(1u << i);
}
static char FakeIsBlocked(void* b) {
  (void)b;
  int32_t num = *(int32_t*)(blocker + 0x28);
  uint32_t* bits = (uint32_t*)(blocker + 0x30);
  for (int i = 0; i < num; i++)
    if ((bits[0] & (1u << i)) && ResolveWeak(*(uint64_t*)(elems + i * 16))) return 1;
  return 0;
}
static wchar_t reasonText[] = L"There are active Abilities ( GA_Test ) blocking saves";
static int freed;
static FString* FakeGetReason(void* b, FString* out) { (void)b; out->data = reasonText; out->num = 10; out->max = 10; return out; }
static void FakeFree(void* self, void* p) { (void)self; assert(p == reasonText); freed++; }
static void* fakeMallocVt[16];
static void* fakeMallocObj[1] = { fakeMallocVt };
static void** fakeMallocGlobal = (void**)fakeMallocObj;

int main(void) {
  InitializeCriticalSection(&g_logLock);
  g_log = GetStdHandle(STD_OUTPUT_HANDLE);
  g_now = FakeNow;
  *(FUObjectItem***)(fakeArray + 0x10) = chunkTable;
  *(int32_t*)(fakeArray + 0x24) = 16;
  g_GUObjectArray = fakeArray;
  fakeMallocVt[9] = (void*)FakeFree;
  g_GMalloc = (void***)&fakeMallocGlobal;
  *(uint8_t**)(blocker + 0x20) = elems;
  g_OnPresented = FakeOnPresented; g_OnEnded = FakeOnEnded;
  g_AvbIsBlocked = FakeIsBlocked; g_AvbGetReason = FakeGetReason;
  g_cfgFix = 1; g_cfgTimeoutMs = 30000;

  void* A = MakeObj(1, 101);
  void* B = MakeObj(2, 102);
  void* C = MakeObj(3, 103);
  uint8_t handler[0x40]; *(void**)(handler + 0x28) = blocker;

  // A starts presenting at t=0 and never ends.
  t_now = 1000000; Hook_OnAbilityPresented(handler, A);
  t_now += 10000;  assert(Fix_AvbIsBlocked(blocker) == 1 && endedCalls == 0);   // 10 s: still legitimately blocked
  t_now += 19000;  assert(Fix_AvbIsBlocked(blocker) == 1 && endedCalls == 0);   // 29 s
  // B starts at 29 s.
  Hook_OnAbilityPresented(handler, B);
  t_now += 2000;   // A at 31 s -> released; B at 2 s -> kept
  assert(Fix_AvbIsBlocked(blocker) == 1 && endedCalls == 1 && lastEnded == A && freed == 1);
  // B finishes normally.
  FakeOnEnded(handler, B); endedCalls--;
  assert(Fix_AvbIsBlocked(blocker) == 0 && endedCalls == 1);

  // C presents, then its object dies (serial reused): must never be passed to the game.
  Hook_OnAbilityPresented(handler, C);
  items[3].serial = 999;
  t_now += 60000;
  assert(Fix_AvbIsBlocked(blocker) == 0 && endedCalls == 1);
  items[3].serial = 103;  // and marked garbage instead
  items[3].flags = 0x10000000;
  assert(Fix_AvbIsBlocked(blocker) == 0 && endedCalls == 1);
  items[3].flags = 0;

  // A presents again later: its clock restarts.
  FakeOnEnded(handler, C); endedCalls--;
  t_now += 5000; Hook_OnAbilityPresented(handler, A);
  t_now += 20000; assert(Fix_AvbIsBlocked(blocker) == 1 && endedCalls == 1);
  t_now += 11000; assert(Fix_AvbIsBlocked(blocker) == 0 && endedCalls == 2 && lastEnded == A);

  // Fix switched off: nothing released.
  g_cfgFix = 0; Hook_OnAbilityPresented(handler, B); t_now += 100000;
  assert(Fix_AvbIsBlocked(blocker) == 1 && endedCalls == 2);

  printf("\nALL LOGIC TESTS PASSED\n");
  return 0;
}
