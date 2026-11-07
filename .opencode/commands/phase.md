---
description: Run one Bolets roadmap step in a fresh child session
subagent: true
model: opencode-go/deepseek-v4-pro
---

You are a fresh-context implementation session for the Bolets mushroom forecast.
You have not seen the parent conversation; rely on the repository files.

Requested phase or step: **$ARGUMENTS**

If the request is empty or says `next`, read `PHASES.md` and run the first step
whose status is not `done`. If the request names a phase with substeps (for
example `2`), run only the first not-done substep and stop. One step per session.

## Before editing

1. Read `PHASES.md`, `PROPOSAL.md`, and `README.md`. Follow the AGENTS.md
   instructions already loaded for this project (global or project-local).
2. Run `git status --short` and `git log --oneline -5`.
   - Do not revert or overwrite changes you did not make.
   - Uncommitted work from a completed step (for example Phase 1) is expected;
     continue without discarding it.
   - If another step is marked `in progress`, or the tree has clearly unrelated
     changes, stop and report a blocker. Only one writer at a time.
3. Read the matching step's Goal, Files, Acceptance, Verification, and Blocked-if.
4. If the step is already `done`, report that and stop.
5. Immediately mark the step `in progress` in `PHASES.md` with the date before
   changing code. This is the lock that prevents two parallel writers.
6. Write a 3–5 bullet plan before changing anything.

## Implementation rules

- Implement only the requested step. Do not start the next step.
- **Do not use the `subagent`/`task` tool.** Do the work in this child session.
  Nested subagents inherit a different model and can stall for hours.
- Keep context small. Do not read large images repeatedly; save maps and probes
  under `/tmp/opencode` and read only the few you need. Prefer text output and
  small scripts over base64 image reads.
- Never pipe a long-running scan through `tail`/`head`; that hides progress and
  makes the session look frozen. Print one line per station or write a progress
  file after each item.
- Prefer coarse sampling first (for example 1 km), then refine only the
  candidate cells. A 0.5 km grid over five stations is hundreds of HTTP calls
  and can take 15+ minutes.
- For curation steps, write candidate zones incrementally after each station.
  Do not spend the whole session researching maps and leave no committed work.
- For zone curation, verify every centroid against CORINE/ICGC forest cover
  before writing it. Accept only 311, 312, 313 or 324, and check that the
  dominant tree matches `forest.dominant`. A coordinate offset from a station is
  not a source.
- Stop and mark the step `blocked` if:
  - a model request fails with `prefill_cap_refused` twice (wait 30 s once),
  - the same tool pattern repeats three times without a file change,
  - the step has been running for more than 45 minutes.
  Record what was learned and where the artifacts are, then return.
- Preserve the current UI and scoring unless the step explicitly changes them.
- Do not invent forest locations, coordinates, soil values, sightings, or
  confidence. Every curated value needs a source and a confidence label.
- Keep best zones, routing and parking free. No paywalls, no hidden answers.
- Do not commit or push unless the user explicitly asks; leave changes for review.
- Prefer small, reviewable changes over a rewrite.
- Use the existing data sources and cache patterns.

## Verification

Run the step's checks, plus:

- `python3 -m py_compile` on every Python file you changed.
- A JS syntax check when the embedded script changed. Extract the script and run
  `node --check`, or use the same check as the previous session.
- `curl` the affected API endpoints.
- Headless screenshots for UI changes, at desktop and mobile widths.

Never mark a step `done` without evidence.

## Update the ledger

Edit `PHASES.md`:

- Set the step status to `done` or `blocked`.
- Add the date, files changed, verification evidence, screenshots if any,
  sources for curated data, and the next step.
- Use the handoff template at the bottom of `PHASES.md`.

## Return

Return a concise handoff:

- status (`done` / `blocked`),
- files changed,
- verification commands and results,
- blockers or decisions needed,
- next step.

If you cannot complete the step safely, mark it `blocked` with the reason and
return. Do not guess.

## Repository snapshot at invocation

Current working tree: !`git status --short`

Recent commits: !`git log --oneline -5`
