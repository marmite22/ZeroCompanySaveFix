# Star Wars Zero Company save fix

Fixes the bug where the game refuses to save, sometimes for the rest of a mission (for example the final mission against Fathom), so you have to finish every phase in one sitting. The bug also stops the mission's autosaves.

Made for Steam build **199049** (patch 1.2). It changes no game files and no save files: it is one small DLL that loads with the game and patches it in memory.

**Tested** in real play on a Steam Machine (Proton). Problem reports are welcome: open an issue and attach `SWZeroCompanyFix.log`.

**Download:** the zip on the [Releases](https://github.com/marmite22/ZeroCompanySaveFix/releases) page. Each one is built by GitHub Actions from this source, not on anyone's PC. To check that, run `gh attestation verify ZeroCompanySaveFix-<version>.zip --repo marmite22/ZeroCompanySaveFix`.

## What goes wrong

The game won't save while an ability's animation ("presentation") is playing. The game's presentation manager starts each animation with `BeginPresentation` and ends it with `StopPresentation`. The C++ versions of these tell the save system "started" and "finished". In between, the ability sits in the game's `FAbilityVisualizationBlocker` list, and **every save is refused, manual saves and the queued autosaves alike**. This blocker does not check the game phase, so it also blocks saving in the exploration sections between fights.

Two kinds of ability keep saves blocked. Both were found by scanning all 834 ability scripts in the game data (see [docs/ability-scan.md](docs/ability-scan.md)):

- **Concussion grenade (`GA_ConcussionGrenade_T1`–`T4`).** This is a bug. Its script overrides `StopPresentation` with an empty event that never calls the original, so "finished" is never sent. Every throw leaves the save block on until the game frees that ability object, which may not happen until the mission ends. No other weapon or ability has this problem.
- **Fathom's `GA_EldritchEcho` and `GA_TheCall`** (also the gunship boss's `GA_GunshipBossAttack` and `GA_GunshipSelectRegions`). These are marked "long running", so the manager's usual 30-second limit doesn't apply. Saves stay blocked for as long as their effect lasts, which in the final fight can be several turns.

## What the fix does

- It notes when each ability's animation starts.
- When the game checks whether it may save, any ability still "animating" after **30 seconds** is released. The fix calls the game's own "presentation ended" handler, the same thing the ability's script should have done. Normal ability animations finish in a few seconds.
- Saving works again, and any autosave the game queued in the meantime goes through.
- Every save blocker is logged when it starts or stops blocking, with the game's own reason text. If saving is still refused, the log says why.

The other save rules are unchanged. In combat you can still save only during your own turn, and not during cinematics or loading.

## Install

Download or copy two files: `version.dll` and `SWZeroCompanyFix.ini` (in `dist/`, or in the release zip, which has the game's folder layout).

### Windows

1. In Steam, right-click **Star Wars Zero Company → Manage → Browse local files**.
2. Put both files in `SWZeroCompany\Binaries\Win64\` (next to the large `SWZeroCompany.exe`, **not** the one in the top folder). You can also extract the zip into the game folder.
3. Play. To check it works, open `SWZeroCompany\Binaries\Win64\SWZeroCompanyFix.log`. It should say `stuck ability save fix: ON`.

### Steam Machine / Steam Deck / Linux (Proton)

1. Copy both files into the same folder as on Windows: `.../steamapps/common/Star Wars Zero Company/SWZeroCompany/Binaries/Win64/` (in desktop mode, use **Manage → Browse local files** in Steam).
2. In Steam, open the game's **Properties → General → Launch options** and enter:
   ```
   WINEDLLOVERRIDES="version=n,b" %command%
   ```
   Without this, Proton ignores the DLL.
3. Play, then check `SWZeroCompanyFix.log` in that folder as above.

## What you'll see in the log

```
[20:14:03.120] [blocker] FAbilityVisualizationBlocker is blocking saves: There are active Abilities ( GA_ConcussionGrenade_T2_C_0 ) blocking saves
[20:14:41.950] [savefix] saves were blocked: There are active Abilities ( GA_ConcussionGrenade_T2_C_0 ) blocking saves
[20:14:41.950] [savefix] ability 000001F3A2B4C000 has been presenting for 38 s without finishing; releasing it so the game can save
[20:14:41.951] [blocker] FAbilityVisualizationBlocker no longer blocks saves
```

`[blocker]` lines show which of the game's save rules is refusing the save. Several are normal, for example `FTacticalSaveBlocker` during the enemy turn, or `FUIStateSaveBlocker` in some menus. If saving is still refused when it shouldn't be, the last `[blocker]` line names the cause.

## Settings (`SWZeroCompanyFix.ini`)

| Key | Default | Meaning |
|---|---|---|
| `LogFile` | 1 | write `SWZeroCompanyFix.log` |
| `StuckAbilitySaveFix` | 1 | release stuck abilities |
| `StuckAbilityTimeoutSeconds` | 30 | how long an ability may animate before it counts as stuck (5–3600) |
| `LogSaveBlockers` | 1 | log each save blocker as it starts or stops blocking |

## Uninstall

Delete `version.dll`, `SWZeroCompanyFix.ini` and the `SWZeroCompanyFix*.log` files from `SWZeroCompany\Binaries\Win64\`. On Linux, also remove the launch option. Nothing else was changed.

## Game updates

At start-up the DLL checks every place it patches, byte for byte. After a game update it searches for each one again. Anything it cannot find exactly, it leaves alone and logs, and the game then runs as if the fix weren't there.

## Limits

- This releases the save block. It doesn't change the grenade's script, so the grenade still never sends "finished" to the other systems that listen for it (audio, voiceover, telemetry). It also doesn't fix the stutter or frozen animations people report with concussion grenades; whether those are connected hasn't been checked.
- For Fathom's long-running abilities, saving is allowed after 30 seconds even though the effect is still running. The effect itself is game state that the save records; only the animation in progress isn't saved.
- The 30 seconds count in real time. If you open the menu within 30 seconds of the ability that got stuck, Save may still be greyed out: close the menu and try again a little later.
- Tested: in real play on a Steam Machine; the patch logic against a fake copy of the game's data structures (`test/test_logic.c`); and loading into the real game on Windows with every patch checked in the live process (`test/loadtest.c`).

## How it was found

The game ships with its debug symbols (`SWZeroCompany.pdb`), so the save code could be read by name:

- `UBrunoSaveGameSubsystem::AreSaveGamesBlocked` asks a list of blockers (`ISaveGameBlocker`, `IsBlocked` = vtable slot 3, `GetReason` = slot 4). `FSaveGameCoordinator::Tick` holds queued autosaves until it returns false.
- `FAbilityVisualizationBlocker` keeps a `TSet<TWeakObjectPtr<UBitReactorGameplayAbility>>`. `UTSB_AbilityEventHandler::OnAbilityPresented` adds to it, and `OnAbilityPresentationEnded` removes from it. Both are bound to `UAbilityEventDispatcher` delegates, broadcast only by `UBRPresentableGameplayAbility::BeginPresentation_Implementation` (+0xE8) and `StopPresentation_Implementation` (+0x168). `APresentationMgr::Tick` calls Stop when an element finishes, or after 30 s of game time unless `IsLongRunning` returns true. A Blueprint that overrides `StopPresentation` without calling the parent never broadcasts Ended. `IsBlocked` only drops abilities that have been destroyed.
- The fix swaps `IsBlocked` in the blockers' vtables, and redirects the one call to `OnAbilityPresented` (inside `execOnAbilityPresented`) through a small jump stub.

Approach modelled on [OblivionRemasteredPerformanceFix](https://github.com/LTSharpe/OblivionRemasteredPerformanceFix).

## Build

Needs [Zig 0.13.0](https://ziglang.org/download/) (a single zip; no Visual Studio needed).

```
ZIG=/path/to/zig ./build.sh test           # dist/version.dll + ini, then runs the logic test
python package.py 1.0.0                    # release/ZeroCompanySaveFix-1.0.0.zip
```

Releases: push a tag such as `v1.0.0`. GitHub Actions builds, tests, packs and attests the zip, then publishes it with `CHANGELOG.md` as the notes.

Load test (needs the game installed and the DLL copied into its folder):

```
zig cc -target x86_64-windows-gnu -O1 -municode -o test/out/loadtest.exe test/loadtest.c -lkernel32
test/out/loadtest.exe "<game>\SWZeroCompany\Binaries\Win64\SWZeroCompany.exe"
```

The load test starts the game under a debugger, stops it at its first instruction (after the fix has patched it, before any game code runs), checks each patch and ends the process. It does not start Steam or touch saves.

`tools/` holds the Python scripts used for the analysis: `syms.py` (symbol lookup via dbghelp), `zdis.py` (disassembler with symbol names; needs `allsyms.tsv` made by `dumpall.py`), `xref.py`, `strs.py`, and `gen.py`, which regenerates `src/offsets.h` for a new game build. The game-data scan tools (`oodle.py`, `iostore.py`, `zen.py`, `kismet.py`, `hashdb.py`, `scan.py`, `dump_ga.py`) are described in [docs/ability-scan.md](docs/ability-scan.md). They need `pip install pefile capstone numpy`.

## Credits and licence

Researched and built by Claude (Anthropic) in Claude Code, directed and tested by Jesse Baker. MIT licence: see [LICENSE](LICENSE). The repository contains no game files.

Not affiliated with or endorsed by Lucasfilm, Bit Reactor or EA.
