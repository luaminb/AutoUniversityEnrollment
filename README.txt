AUTOMATIC UNIVERSITY ENROLLMENT - PROJECT BUILD 0.6

PURPOSE
-------
Enroll eligible unplayed NPCs in Discover University in two situations:
1. Existing YOUNGADULT Sims: one sweep after the first world zone reaches
   RUNNING in the current game session.
2. New YOUNGADULT Sims: immediately after a TEEN-to-YOUNGADULT age transition.

ELIGIBILITY AND SAFEGUARDS
--------------------------
- Only NPCs in households that have never been played.
- Excludes player/played households, selectable Sims, and player Sims.
- Excludes Sims with an existing enrollment or previous university history.
- The startup sweep is guarded to run once per game session.
- One Sim failing the sweep does not stop processing other Sims.
- Does not create, replace, or regenerate Sims.
- University and major are selected randomly using the game's native
  University helper methods; enrollment follows the native Sim-template
  sequence and requests three courses.
- The original age-change and zone spin-up methods run first. Mod-side
  exceptions are logged and caught.

BUILD REQUIREMENTS
------------------
The Sims 4 script runtime uses Python 3.7 bytecode. GitHub Actions automation
uses Python 3.7.17 to create AutoUniversityEnrollment.ts4script.

BUILD
-----
Open the Actions tab and select "Build Auto University Enrollment".
Run the workflow manually, or push a change to a watched source file.
The workflow runs mocked tests, compiles the script, and uploads the artifact
named AutoUniversityEnrollment-ts4script.

INSTALL AFTER BUILD
-------------------
Extract AutoUniversityEnrollment.ts4script into:
Documents\Electronic Arts\The Sims 4\Mods\AutoUniversityEnrollment\
Enable Script Mods in Game Options > Other and restart the game.

TESTING STATUS
--------------
The mocked regression suite checks control flow only. It does not emulate the
game engine or prove compatibility in The Sims 4. In particular, the
Zone.do_zone_spin_up callback, SimInfoManager enumeration, and enrollment
sequence require in-game validation. This project is experimental.
