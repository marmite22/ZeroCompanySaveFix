# Which abilities can block saving

This scan of build 199049 decoded the scripts of **all 834 gameplay abilities** (`GA_*` assets in `pakchunk0`/`pakchunk1`), plus the other 2,591 assets under `Abilities/`. All parsed with 0 errors: every function's decoded size matched the size the game stored exactly.

## How saving gets blocked

`APresentationMgr` (C++) starts each ability's animation with `BeginPresentation` and ends it with `StopPresentation`. The **C++** versions of these send "presented" and "presentation ended" to the save blocker (`UAbilityEventDispatcher` +0xE8 / +0x168). Nothing else sends them. Between the two, saves are refused.

The manager calls `StopPresentation` when the animation reports finished, or after **30 s of game time**. Two things defeat that:

1. A script **overrides `StopPresentation` without calling the parent**. The C++ version never runs, so "ended" is never sent. The save block lasts as long as the ability object exists.
2. A script **returns true from `IsLongRunning`**. The 30 s limit then doesn't apply, and saves stay blocked until the effect says it's finished.

(No script calls `APresentationMgr::RefreshStartTime`, the other way to keep a presentation alive.)

## Results

### Bug: "ended" is never sent

| Ability | BeginPresentation reaches C++ | StopPresentation reaches C++ | Chain |
|---|---|---|---|
| `GA_ConcussionGrenade_T1` | always | **never** (empty override) | → `GA_TypicalThrowItem` → `BRPresentableGameplayAbility` |
| `GA_ConcussionGrenade_T2` | always | **never** (inherits T1) | → `GA_ConcussionGrenade_T1` → … |
| `GA_ConcussionGrenade_T3` | always | **never** (inherits T1) | → `GA_ConcussionGrenade_T1` → … |
| `GA_ConcussionGrenade_T4` | always | **never** (inherits T1) | → `GA_ConcussionGrenade_T1` → … |

Every other ability reaches the C++ `StopPresentation` on every path (830 of 834). Ten never reach `BeginPresentation` and seven reach it on only some paths; none of those can block a save.

### Long-running: blocks saving while the effect lasts (by design, but long)

| Ability | Where | Notes |
|---|---|---|
| `GA_EldritchEcho` | Fathom (`Enemy/Coil/Fathom`) | `IsLongRunning` returns true; finishes when `SM_EldritchEcho` ends |
| `GA_TheCall` | Fathom (`Enemy/Coil/Fathom`) | `IsLongRunning` returns true; finishes when `SM_TheCall` ends; applies `ObeysTheCall` |
| `GA_GunshipBossAttack` | gunship boss | `IsLongRunning` returns true |
| `GA_GunshipSelectRegions` | gunship boss | `IsLongRunning` returns true |

All four send "ended" correctly once they finish.

## The fix

`SWZeroCompanyFix` releases any ability that has held the save block for more than 30 s (real time), which covers both cases.

## Reproduce

Tools in `tools/` (Python 3, `pip install pefile capstone numpy`):

- `oodle.py` loads the game's own Oodle decoder from `SWZeroCompany.exe` (its import table is filled in by the script; the game's code is not run).
- `iostore.py` reads `.utoc`/`.ucas` (TOC version 8).
- `zen.py` reads zen package headers: names, imports, exports, imported package names.
- `kismet.py` decodes script bytecode. It tracks in-memory offsets for jumps, and resolves script imports with the game's own `CityHash64`.
- `hashdb.py` maps script-import hashes to class and function names from the PDB (needs `ufuncs.txt`/`uclasses.txt`, made from `allsyms.tsv` with `grep -oP`).
- `scan.py` runs the whole scan and writes `scan.json`.
- `dump_ga.py <asset> <function...>` prints one script's statements and calls.
