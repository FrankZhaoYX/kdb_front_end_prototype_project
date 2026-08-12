---
mode: agent
description: Implement the next unchecked phase from PLAN.md, verify it, and update the ledger.
---

Read `PLAN.md`. Find the first unchecked box in its Progress Ledger — that is
your only task this turn.

1. Read that phase's section in `PLAN.md` in full.
2. For every file marked `[copy]`, read it from `reference/<path>` and write
   it to `<path>` unchanged — do not regenerate its contents from the prose
   description.
3. For any file the phase says to write rather than copy, write it following
   `AGENTS.md` and whichever file under `.github/instructions/` applies to
   the paths you're touching.
4. Run the phase's acceptance command exactly as written.
5. If it passes: tick that phase's checkbox in `PLAN.md`'s Progress Ledger
   and stop. Report the result in one or two sentences — do not paste file
   contents or full command output back into chat, just the pass/fail
   summary.
6. If it fails: check `KNOWN-PITFALLS.md` for a matching entry before
   attempting a fix. Fix only within this phase — do not touch files
   belonging to an already-ticked phase, and do not start the next phase.
7. If the phase requires a decision only the user can make (a compliance
   question, a missing credential, a platform difference not already
   covered in `PLAN.md`), stop and ask instead of guessing.

Do not run more than one phase in a single invocation of this prompt, even
if the next phase looks trivial — each phase is its own checkpoint.
