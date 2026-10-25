## 1.0.0-beta.1

First release, for Steam build 199049 (patch 1.2). **Beta:** tested by loading into the real game with every patch checked, not yet in a full mission.

- Saving no longer stays blocked for the rest of a mission after a **concussion grenade**. Its script never tells the game the throw animation has finished, so saves and autosaves were refused until the mission ended. Any ability still "animating" after 30 seconds is now released.
- Also covers Fathom's long-running abilities (`GA_EldritchEcho`, `GA_TheCall`), which block saving for as long as their effect lasts.
- `SWZeroCompanyFix.log` lists every save blocker as it starts or stops blocking, with the game's reason.

Install: extract the zip into the game folder (Steam → Manage → Browse local files). On Steam Machine / Steam Deck / Linux, also set the launch option `WINEDLLOVERRIDES="version=n,b" %command%`. See the README for details.
