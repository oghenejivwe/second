# COMMUNICATION PROTOCOL — Second

Every instance answers on its own log file — `prompts/instance-N-<name>.md`.
That file is a conversation between the CTO and one instance. **The file IS the
message.** Chat output is only a one-line relay.

## The shape of a log file

```
<the brief>          immutable — never edited after the first task
---
## <INSTANCE> — turn 1 · <ISO timestamp>
## CTO — turn 1 · <ISO timestamp>
## <INSTANCE> — turn 2 · <ISO timestamp>
...
WAITING ON: <who>    ALWAYS the last line of the file
```

## Rules

1. **Append-only.** Never edit a prior turn. A correction is a NEW turn, or an
   `ADDENDUM` that references the one it corrects. The record of a wrong call and
   its reversal is more useful than a clean file.
2. **Matched turn numbers.** Instance turn N is answered by CTO turn N.
3. **The ball-tracker is the last line**, and there is exactly one:
   `WAITING ON: CTO` or `WAITING ON: <INSTANCE>`. Overwrite it every turn. It
   must be **one line** — it is read mechanically.
4. **On Windows, read it with PowerShell `Get-Content -Tail 1`**, never bash
   `tail`. CRLF makes bash report the wrong last line.

## Instance turn format

```
## <INSTANCE> — turn N · YYYY-MM-DDTHH:MMZ
**asks:** <one line: what you need to proceed, or "none">
**phase:** <research | building | done — ready for review | blocked>

<Body, under 200 words outside fenced blocks. Conclusion first. Tables for
state. Bold the key terms. Ground every claim — file:line, or command output.
Never assert what you have not checked.>

Include, every time:
- every file you changed and what changed in each
- the mutation you watched go RED for each guard you added
- WHAT THE BRIEF GOT WRONG — say it plainly
- `git status --porcelain`, so the reviewer sees your exact footprint
- test count vs baseline; whether the typechecker is clean

---
WAITING ON: CTO — <what you need>
```

## CTO turn format

Same shape, with **`verdict:`** instead of **`asks:`**:

```
## CTO — turn N · YYYY-MM-DDTHH:MMZ
**verdict:** <approved | changes requested | blocked — and why, in one line>
**phase:** <the phase the instance is now in>

<Body. Say what I verified MYSELF before ruling. Where the instance corrected
me, say so explicitly. Rulings numbered, each with its reason — a ruling without
a reason gets re-litigated next turn.>

---
WAITING ON: <INSTANCE> — <what to do next>
```

## The relay

After writing a turn, the instance gives the user **one fenced line**:

```
connectors, read and update prompts/instance-2-connectors.md
```

Fenced, not inline — a fenced block renders a copy button. The user pastes it to
the other session. **They do not read turn bodies.** Never summarise the log in
chat; that duplicates the record and the user reads the wrong copy.

## What "blocked" means

An instance that needs something it does not own — a shared type, a route, an env
var, a decision — **stops and reports**. It does not work around it with a
temporary approximation. Temporary approximations on a critical path are how
defects reach production wearing a comment that says they are temporary.

## One thing specific to this build

There is a **hard deadline: 2026-09-14 17:00 PDT**. When you are choosing
between reporting early with a smaller package and reporting late with a bigger
one, report early. A blocked CTO with four hours left is worse than a thin turn.

If you are about to spend more than **45 minutes** on something the brief did
not anticipate, stop and report instead. That is not a failure; it is the
schedule working.
