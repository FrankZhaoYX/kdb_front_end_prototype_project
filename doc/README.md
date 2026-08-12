# KDB Report Console — Copilot Agent Rebuild Kit

This is a self-contained package for rebuilding the KDB Report Console
prototype on a different machine using **GitHub Copilot** (Chat agent mode in
VS Code, or the Copilot coding agent) instead of Claude Code — put together
because the original build environment isn't available where you're working
now.

## What's in here

```
PLAN.md                          the build plan Copilot should follow, phase by phase
AGENTS.md                        non-negotiable design rules (read once per session)
KNOWN-PITFALLS.md                every real failure mode hit building the original — read before debugging
.github/
  copilot-instructions.md        short, auto-loaded on every Copilot request in this repo
  instructions/*.instructions.md longer, topic-scoped rules that load only for matching files
  prompts/*.prompt.md            reusable slash-invokable procedures ("skills")
reference/                       the actual working, tested source (40 files, 44/44 tests passing)
```

`reference/` is a full copy of the git-tracked source tree from the original
build — no `.venv`, no generated data files, no logs, just the 40 files that
make the system what it is. `PLAN.md` is written to have Copilot **copy from
here rather than regenerate from scratch**, which is what makes the rebuild
cheap: most of the work is "read this file, write it there, run this
command," not "design this from a description."

## How to use this

1. Unzip this into a new, empty folder — that folder becomes your project
   root. `reference/` should sit alongside `PLAN.md` at the top level.
2. Open the folder in VS Code with GitHub Copilot Chat installed, switch to
   **Agent mode**, and either:
   - type `/implement-phase` repeatedly (once per turn — it does exactly one
     `PLAN.md` phase and stops), or
   - just say "follow PLAN.md" and let it work through the ledger.
3. **Start a new chat session for each phase**, or every few phases. This is
   the single biggest cost saver: `PLAN.md`'s Progress Ledger lets a fresh
   session pick up exactly where the last one stopped, without replaying any
   prior conversation.
4. Read `PLAN.md`'s **Phase 0** yourself before letting Copilot loose — it's
   a preflight check, including one real compliance question ("is fetching a
   free KX Community license over the network okay on this machine?") that
   only you can answer.

## What this rebuild produces

The same prototype described in `reference/DESIGN.md` and
`reference/MANUAL.md`: a browser front-end where a user picks a report
category, then a report, fills in parameters generated from a CSV catalog,
and gets back a table, an HTML page, or a PDF — talking to a real kdb+
process (embedded KDB-X via PyKX) the whole way, no mocks.

## If you can't bring `reference/` at all

If policy turns out to forbid moving even this prototype code between
environments, `reference/DESIGN.md` and `reference/MANUAL.md` (both plain
prose, no code) are detailed enough for Copilot to reconstruct the system
from description alone — it will just cost far more tokens and time than the
copy-based path `PLAN.md` is written for. In that case, tell Copilot to skip
every `[copy]` instruction in `PLAN.md` and write each file fresh from the
relevant section of those two documents instead.

## Once it's built

Everything after that is normal development — `AGENTS.md` and the
`.github/instructions/` files keep applying, and `/add-report` and
`/verify-stack` (also in `.github/prompts/`) are there for adding new reports
or sanity-checking the stack going forward.
