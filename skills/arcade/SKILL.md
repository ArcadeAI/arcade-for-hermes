---
name: arcade
description: How to act in business apps through Arcade for Hermes under the look/draft/ship policy, with a work-order ID on every call and a human approval before anything ships.
---

# Working through Arcade for Hermes

You act in external apps (GitHub, Google Docs and more) as your own role's Arcade principal. Every
call is checked against the policy before it leaves Hermes and leaves a receipt. Three verbs:

| Verb | Meaning | What happens |
|---|---|---|
| look | read | runs, receipt |
| draft | create or edit an artifact | runs, receipt |
| ship | anything others see, or anything that moves money | waits for the human in Hermes's approval gate, then runs, receipt |

Anything the policy does not name is denied before Arcade is called. A denial is final for your
role: do not retry it with different arguments to get around it, and do not ask another role to do
it for you unless the human asks.

## Steps

1. Start with `arcade_whoami` once per task: it tells you your role, your principal and your grants.
2. Find the exact tool name with `arcade_search_tools` (query by words, or by toolkit). The result
   shows the verb each tool gets and whether your role may call it. Never guess a tool name.
3. Call `arcade_execute` with `tool`, `input` and the `work_order` ID you are working on (for
   example `BC-2026-001`). Put the same ID in titles, comments and documents you create so the audit
   trail lines up.
4. If the result is `authorization_required`, call `arcade_authorize` for that toolkit, show the
   link to the human verbatim, and retry the same call only after they say they consented. Never open
   the link yourself and never ask for a wider grant than the tool needs.
5. Before a ship action, say in one sentence what will change and for whom, then make the call; the
   approval card is the human's decision. If it is denied or times out, report that and stop.
6. When the human asks what happened, point them to `/arcade audit <work_order>`.

## Rules

- Prefer look before draft, and draft before ship.
- One work order per task; never invent a new ID.
- Do not paste tokens, links from `arcade_authorize`, or document bodies into receipts or issues.
- In a cron or unattended run a ship action returns `NEEDS_HUMAN`; do not work around it.
