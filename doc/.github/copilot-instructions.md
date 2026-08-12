<!--
Repo-wide custom instructions for GitHub Copilot Chat / Copilot coding agent.
This file is included in EVERY Copilot request made in this repository, so it
is kept deliberately short — detail belongs in PLAN.md, AGENTS.md, and the
path-scoped files under .github/instructions/, which only load when relevant.
-->

# Copilot instructions — KDB Report Console

1. Before writing any code, read `PLAN.md` (build order + current progress
   via its checkbox ledger) and `AGENTS.md` (non-negotiable design rules).
   Do not restate their contents in chat — just follow them.
2. Prefer copying a file verbatim from `reference/<same path>` over writing
   it from scratch. The reference implementation is already built, tested,
   and debugged (44/44 tests passing). Only hand-write code where `PLAN.md`
   says to, or when actively fixing something after the initial build.
3. Work one `PLAN.md` phase per turn. Stop and tick its checkbox when the
   phase's acceptance check passes; don't continue into the next phase
   unprompted.
4. Before debugging anything under `kdb/`, `app/kdbclient.py`, or
   `app/__init__.py`, check `KNOWN-PITFALLS.md` — most failures there are
   silent (wrong behavior, no error) and expensive to rediscover by trial
   and error.
5. Don't paste full file contents into chat responses. The file is on disk;
   summarize the change in one sentence.
6. This project deliberately has no authentication and no mock kdb+ backend.
   Don't add either speculatively — see `AGENTS.md` rules 5 and 7.
