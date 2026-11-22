AUTOMATIC UNIVERSITY ENROLLMENT - PROJECT BUILD 0.5

PURPOSE
-------
When an NPC ages from TEEN to YOUNGADULT, attempt to enroll the Sim in
Discover University, only if the Sim belongs to a household that has never
been played and has no current or previous university enrollment history.

RULES
-----
- Random university and major selected through the same helper methods used
  by the game's native Sim-template enrollment routine.
- Requests three courses, following the game's native Sim-template routine.
- Excludes player households, played households, selectable Sims, Sims with
  an existing enrollment, and Sims with previous majors/courses.
- Does not create, replace, or regenerate Sims.
- The original age-change method runs first; mod errors are caught so the
  aging operation itself is not intentionally interrupted.

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
game engine or prove compatibility in The Sims 4. The compiled script must
still be tested in-game. This project is experimental.
