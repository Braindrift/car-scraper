---
description: Run a batch of CAR tickets end to end — each is implemented, tested, committed, pushed, and closed inside its own isolated subagent.
argument-hint: CAR-a to CAR-b | CAR-a CAR-b … | CAR-a | all open CAR
allowed-tools: Agent, Bash(git *), Bash(gh *), Read
---

Run the ticket batch described by **$ARGUMENTS** for `Braindrift/car-scraper` to completion.
This command is a thin **orchestrator**: it resolves the ticket list, then hands each ticket —
whole — to its own isolated subagent that implements, tests, and ships it. Only a one-line
result per ticket returns to this thread, so it stays flat no matter how many tickets run.

This is a single-repo project, so tickets are dispatched **sequentially, one at a time** —
each subagent starts from a clean, up-to-date `main`, and the next is only dispatched once the
previous has shipped (or the batch is stopped). Never have more than one ticket's subagent
active at once; concurrent commits/pushes into the same repo would conflict.

Do **not** implement or ship anything yourself in this thread — all of that happens inside the
subagents. Your job here is: resolve, confirm once, dispatch, gate, report.

## Steps

1. **Resolve the batch.** `CAR-<n>` = issue `#<n>` in `Braindrift/car-scraper` (see "Ticket
   naming" in CLAUDE.md). Parse `$ARGUMENTS`:
   - `CAR-3 to CAR-14` → inclusive numeric range; silently skip numbers with no open issue.
   - `CAR-3 CAR-7 CAR-12` → explicit list, kept in the given order.
   - `CAR-4` → a single ticket.
   - `all open CAR` → `gh issue list -R Braindrift/car-scraper --state open --json number,title`,
     sorted ascending.

   Print the resolved ordered list (number + title) and **confirm once** before starting. This
   is the only planned interruption — once the user okays it, the batch runs unattended to the
   roll-up.

2. **For each ticket, in order:**

   a. Make sure the working tree is clean and `main` is up to date (`git status`, `git pull`).
      If the tree isn't clean for reasons unrelated to this batch, stop and ask rather than
      stashing or discarding anything.

   b. Dispatch one subagent (`Agent`, subagent_type `general-purpose`) with a prompt that gives
      it the ticket id and instructs it to do the **whole ticket** in its own context:

      > Implement and ship ticket **CAR-n** for `Braindrift/car-scraper`. The repo is at
      > `E:\Projects\ProjectsPython\CarScraper_2.0` (single-repo project — work in this
      > directory, target `gh ... -R Braindrift/car-scraper` explicitly).
      >
      > 1. Read the issue: `gh issue view n -R Braindrift/car-scraper`. Note its title and
      >    **Definition of Done**.
      > 2. Implement **only** this ticket's scope, following CLAUDE.md's architecture,
      >    layering, and SoC/SRP rules (`scrapers/` vs `services/` vs `db/` vs `api/` vs
      >    `web/` vs `cli/` boundaries, `CarListingDTO` as the normalization boundary, no god
      >    classes/files). Don't bundle unrelated cleanup.
      > 3. **Autonomy:** make reasonable calls on small ambiguities (naming, file placement,
      >    minor schema details) and record them as "Assumptions" in the closing comment.
      >    **Escalate instead of guessing** — stop without committing — only when a genuine
      >    design decision is needed, the DoD is too under-specified to implement faithfully,
      >    or the ticket's intended approach looks fundamentally wrong. In that case return
      >    `BLOCKED: <the specific decision needed>` and nothing else.
      > 4. **Verify.** Run what's applicable: `ruff check .`, `black --check .`, `pytest`, and
      >    `alembic upgrade head` if migrations were added. Split the DoD into **Verified**
      >    (covered by these commands) vs **Unverified** (rendered dashboard, live-site
      >    Playwright run, Task Scheduler — anything you can't exercise headlessly). If
      >    ruff/black/pytest aren't green, fix it before shipping; if you can't get them
      >    green, stop and report rather than shipping red.
      > 5. **Commit** only this ticket's files. Subject: `CAR-n <summary>`, short body on what
      >    changed and any non-obvious additions. Include the `Co-Authored-By` trailer.
      > 6. **Push** to `main`.
      > 7. **Closing comment + close issue:** `gh issue comment n -R Braindrift/car-scraper -F -`
      >    then `gh issue close n -R Braindrift/car-scraper`. Lead with `Done in <commit>.`,
      >    then **Verified**, **Needs manual verification** (phrased as checks the user must
      >    run), any seams left for follow-up tickets, and any "Assumptions".
      > 8. **Return ONE line, nothing else:**
      >    - `shipped <sha>: <one line on what the user can now see or do>` — only if the core
      >      DoD is in the Verified bucket.
      >    - `shipped-unverified <sha>: <what shipped> — NEEDS MANUAL VERIFY: <exact check>` —
      >      if the core DoD rests on unverified behavior. Ship it, but say so.
      >    - `BLOCKED: <the decision needed>`.

3. **Gate on the result.**
   - `BLOCKED` (or the subagent couldn't get the suite green) → **stop the entire batch**. Do
     not dispatch further tickets. Report the blocked ticket, its question, and which tickets
     already shipped vs. not yet started. Wait for the user.
   - `shipped` / `shipped-unverified` → record it (keeping the `NEEDS MANUAL VERIFY` note
     verbatim) and continue to the next ticket.

4. **Roll-up report.** After the last ticket ships (or the batch stops), print a table:

   | Ticket | Status | Commit | What shipped |
   |--------|--------|--------|--------------|

   Use the status verbatim (`shipped` vs `shipped-unverified`). Below the table, add a
   **"Needs your eyes before trusting"** section listing every `shipped-unverified` ticket with
   the exact check the user must run, plus any notable assumptions subagents recorded. If the
   batch stopped early, list the blocked ticket and the not-yet-started ones.

## Guardrails

- This thread only orchestrates: resolve, confirm once, dispatch, gate, report. Implementing
  and shipping happens entirely inside the per-ticket subagents.
- Sequential only — never have more than one ticket's subagent active at a time.
- Always use the `CAR-<n>` prefix exactly as it maps to the GitHub issue number — never drop,
  renumber, or guess it.
- The upfront list confirmation is the only planned interruption. Past it, the batch runs to
  the roll-up unless a subagent returns `BLOCKED`.
- Don't commit, push, or close an issue if verification failed or the work is `BLOCKED`.
