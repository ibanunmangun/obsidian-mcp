# Freya - Mistake Log

A running log of errors encountered and lessons learned across all sessions.

---

## [2026-05-12] — First Real Entry
**Context:** Working on widget X.
**Mistake:** Used wrong import path.
**Root Cause:** Module was renamed in v2.
**Fix:** Updated import to v2 module.
**Lesson:** Verify imports after upgrades.

## [2026-05-13] — Multiline Field Entry
**Context:** Reviewing PR for feature Y.
This is a continuation of context.
**Mistake:** Approved without running tests.
**Root Cause:** Time pressure plus assumption that CI would catch it.
**Fix:** Re-ran tests locally; CI passed but caught a flake later.
**Lesson:** Always run tests locally before approving urgent PRs.

## [2026-05-14] — Malformed Missing Fix
**Context:** Doing thing.
**Mistake:** Did wrong thing.
**Root Cause:** Misread spec.
**Lesson:** Read carefully.

## Random Header Without Date Pattern
This is just a section heading and should be ignored by the parser.

## [2026-05-15] — Last Valid Entry
**Context:** Final regression test.
**Mistake:** Forgot to update changelog.
**Root Cause:** Habit.
**Fix:** Added changelog entry.
**Lesson:** Add changelog as part of the PR template.
