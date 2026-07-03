# Workmap "Today" Redesign — Design Spec

Date: 2026-07-03
Status: Approved for planning

## Problem

Capturing a task requires picking a goal and filling fields — too much ceremony
for a quick thought. There is no visible momentum: completing tasks gives no
satisfying feedback, so the tool doesn't pull the user back day to day. Goals
feel like a separate structure to remember rather than something that emerges
from daily action.

Goal: reduce capture friction to near-zero, add a habit-forming feedback loop
(streak + activity heatmap, GitHub-contributions-style), and extend the
existing AI pipeline to reduce decision-paralysis (what to do next) and
task-size intimidation (breaking down vague/large tasks) — without adding new
infra beyond what's in `local_store.py` / `server.py` today.

## Information Architecture

- **Home = Today** (new default route). Sidebar becomes: `Today` · `Board`
  (flat filterable to-do list, replaces the old kanban board) · `Goals`
  (settings/rollups only) · `Settings`.
- Goals remain a real entity (progress rollups, per-goal settings unchanged)
  but the UI never requires drilling into a goal page for daily use. Every
  task shows its goal as a **tag chip**; any list (Today, Board) can be
  filtered/sorted by tag. AI resolves `goal_id` for captured tasks in the
  background — the user is never required to visit Goals to capture or act.
- Today screen, top to bottom:
  1. Inbox capture bar — single input, always focused, pinned at top.
  2. Streak + heatmap strip — current streak, freeze status, ~90-day dot grid.
  3. Next actions — AI-picked 1–3 tasks to act on right now.
  4. Digest banner — collapsible one-liner summary, closed by default.

## Task Completion Model (To-Do Style)

- Every task row has a checkbox. Checking it strikes through the title and
  sets status to `done` in one action — no separate "mark complete" control.
- A task may have a **subtask checklist** — small indented to-dos, expandable
  under the task row. Checking a subtask strikes it through.
- **Auto-complete**: when the last subtask is checked, the parent task
  auto-completes (strikethrough + `done`), no extra tap required.
- This checklist is also the landing spot for the AI subtask-breakdown
  capability (see AI Capabilities below) — AI-proposed subtasks populate the
  same checklist structure, not a separate UI.
- Data model: subtasks are child tasks (`parent_task_id` on the existing
  `tasks` table) rather than a new entity — reuses `create_task`/
  `update_task`/`complete_task` as-is. Parent auto-complete is a new check in
  `complete_task`/subtask-completion path: after marking a subtask done,
  check if all siblings are done and cascade.

## Board: Flat Filterable To-Do List

Kanban columns (backlog/board/done) are removed. Board becomes one
scrollable checklist — same checkbox/strikethrough/subtask behavior as
Today — filterable by **tag (goal)** and **status** via chips/dropdowns
instead of spatial columns. This is the browse-everything view: "show me
everything tagged Fitness" or "show me everything still backlog."

## Capture & AI Classification Flow

- Typing into the inbox bar and pressing enter creates a task immediately as
  `backlog` with the raw text as title. No blocking wait, no goal picker.
- Async classification reuses the existing `create_ai_draft` /
  `_infer_task_payload` pipeline (Ollama with deterministic fallback) to
  refine title/description, infer `goal_id`, `priority`, `estimate`, `tags`.
- **Confidence gate**: high-confidence classification (clear goal match, clear
  intent) auto-applies silently; the task updates in place and a small
  non-blocking toast confirms ("Sorted into Fitness").
- Low-confidence results do not block or force a review modal. They increment
  a small "Needs a look" badge count near the inbox bar. The user opens it
  when they want to; ignoring it costs nothing — the task remains usable as
  originally captured.
- This is the one deliberate trade-off in the design: it optimizes for
  zero-friction capture over guaranteed-correct classification. Misclassified
  low-priority items are acceptable; forcing a review step every time is not.

## Activity, Streak & Heatmap

- New table: `activity_log(date TEXT PRIMARY KEY, count INTEGER, minutes INTEGER)`,
  one row per calendar day (local time).
- A day's count increments on any of: task completed, progress logged, focus
  session ended, task captured via the inbox. ("Any engagement" counts, not
  only completions — rewards showing up on light days.)
- Streak is computed on read as the number of consecutive days (ending today
  or yesterday) with `count > 0`. It is not stored separately, so it cannot
  drift out of sync with `activity_log`.
- **Streak freeze**: one freeze token available per rolling 7-day window. On
  the first request of a new day, if yesterday had `count == 0` and a freeze
  token is available, the streak is preserved and the token is consumed
  instead of the streak resetting to 0. If no token is available, the streak
  resets normally.
- Heatmap renders the last ~90 days as a CSS grid, 5 shades by `count`
  (0 = empty, 4 = darkest), no charting library required.
- Today header shows: `🔥 6 day streak · 1 freeze left`.

## AI Capabilities

All three extend the existing Ollama/deterministic-fallback pipeline already
in `local_store.py` — no new AI infrastructure, only new prompts/heuristics
layered on the existing `create_ai_draft`-style functions.

**Next actions** — extends the existing `suggest_next_tasks()` scoring (due
pressure, staleness, priority) with a lightweight time-cost signal: tasks can
be tagged `quick` (<15 min) or `deep`. Today can be filtered "I have 10
minutes" vs "I have an hour." AI surfaces the top 1–3 matches as cards with a
one-tap "Start" (opens a focus session) or "Snooze."

**Digest** — reuses the existing `summarize_workspace()` function. Generated
once per day and cached; rendered as a single collapsible line at the bottom
of Today (what moved yesterday, what's gone stale, streak status). No push
notifications, no popups — read only if the user chooses to expand it.

**Subtask breakdown** — triggered when a captured task's title looks large or
vague (heuristic: >8 words, or contains "and"/"then", or the AI classifier
itself flags low decomposability during classification). AI proposes 2–4
subtasks, rendered directly into the same to-do checklist described in Task
Completion Model above (not a separate structure). One tap ("Split") creates
them as child tasks (`parent_task_id` set, same goal); ignoring the
suggestion leaves the original task untouched as a single checkable item.

## Visual Style

Light, warm, Notion-style — replaces `frontend/src/App.css` rather than
patching it, since the Today layout is enough of a structural change that a
fresh stylesheet is cleaner than layering on the old one.

- Background off-white (`#FAF9F6`); cards pure white with a 1px hairline
  border; soft shadow on hover only, not at rest.
- Single warm accent (amber/coral) reserved for: streak fire, primary
  actions, and the heatmap's darkest shade. Everything else neutral
  gray/ink text — one accent, not a palette.
- Rounded-sans or serif for headings, system sans for body. Small sizes,
  generous line-height and whitespace.
- Heatmap dots use the accent color at 5 opacity steps (GitHub pattern,
  warm-toned instead of green).
- Motion is subtle only: toast fade-ins for AI auto-sort. No shame-based UI —
  no red states, nothing that draws attention to inaction.

## UI Diagrams (text mockups)

### Today screen

```
┌─────────────────────────────────────────────────────────────┐
│  Workmap                                  [Today] Board Goals │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ✏️  Capture anything...                              [↵]     │  ← inbox bar
│                                                               │
│  🔥 6 day streak · 1 freeze left        Needs a look (2) ›   │
│  ┌ 90-day activity ─────────────────────────────────────┐   │
│  │ ▢▢▤▤▥ ▤▥▦▢▢ ▥▦▧▤▢ ▢▤▥▦▧ ▧▦▥▤▢ ...                    │   │  ← heatmap dots
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  Next actions                          [10 min] [1 hr] [any] │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ ○  Reply to landlord email          #Home      Start › │  │
│  │ ○  Stretch + 10 pushups             #Fitness   Start › │  │
│  │    ↳ ☐ warm up   ☐ 10 pushups   ☐ stretch 5 min       │  │  ← subtask checklist
│  │ ○  Draft Q3 goals doc               #Work      Start › │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  ▾ Digest: 3 stale in #Fitness, streak steady, 2 done today  │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Board (flat filterable to-do list)

```
┌─────────────────────────────────────────────────────────────┐
│  Workmap                                  Today [Board] Goals │
├─────────────────────────────────────────────────────────────┤
│  Filter:  #Fitness ✕   #Work   #Home        Status: All ▾    │
├─────────────────────────────────────────────────────────────┤
│  ☑  ~~Book dentist appointment~~              #Home           │
│  ☐  Draft Q3 goals doc                        #Work           │
│  ☐  Stretch + 10 pushups                      #Fitness        │
│      ↳ ☑ ~~warm up~~   ☐ 10 pushups   ☐ stretch 5 min        │
│  ☐  Refactor onboarding flow                  #Work           │
│  ☑  ~~Pay electricity bill~~                  #Home            │
└─────────────────────────────────────────────────────────────┘
```

- Checked items show strikethrough (`~~text~~` above stands in for that).
- Tag chips (`#Fitness`, `#Work`, `#Home`) are the goal, clickable to filter.
- Subtask rows indent under the parent, same checkbox behavior; parent
  auto-checks when all children are checked (see "10 pushups" example above —
  still open, so "Stretch + 10 pushups" stays unchecked).

## Explicitly Out of Scope

- Push notifications / external reminders for the digest.
- Swipe-to-triage review queue (rejected in favor of the badge-count model).
- New AI infra (no new model, no new service) — everything builds on the
  existing pipeline in `local_store.py`.
- Multi-user / auth — this remains a local-first single-user tool.
- Free-form/arbitrary tags — tags are goals only, no separate tagging system.
- Kanban board — removed entirely in favor of the flat filterable list.
- Multi-level subtasks (subtasks of subtasks) — one level of nesting only.

## Testing Notes

- Backend: unit tests for streak computation (consecutive-day logic, freeze
  consumption/expiry at week boundaries) and for `activity_log` increments
  firing on each of the four trigger events.
- Backend: existing `_infer_task_payload`/`create_ai_draft` confidence
  thresholds need an explicit, testable definition (e.g. a numeric score) so
  the "auto-apply vs needs-a-look" gate is deterministic and testable without
  Ollama running (deterministic fallback path).
- Backend: unit tests for subtask auto-complete cascade (checking last
  subtask completes parent; checking a subtask when siblings remain open
  does not) and for tag/status filtering on the flat Board list.
- Frontend: no new component should require a runtime AI response to render
  — inbox capture, heatmap, and streak header must all work with the
  deterministic fallback alone, matching the existing "AI unavailable" rule
  in `CLAUDE.md`.
