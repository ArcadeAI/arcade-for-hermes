---
name: found-a-company
description: Turn a founder's business idea into a running Hermes company on Arcade. Research the idea, choose roles and the Arcade apps each one needs, and save a draft the founder starts with /arcade found.
---

# Found a company

The founder typed an idea ("a shirt shop that sells drops on X", "bookkeeping for dentists"). Your
job is to turn it into a company spec, not to start the company. Starting it changes permissions,
so only the founder does that, with `/arcade found`.

## 1. Research (15 minutes of work, not a report)

Use the search tools you have through Arcade (`arcade_search_tools` with words like "search",
"news", "web": Exa, Firecrawl, GoogleSearch, GoogleNews, Reddit). Find out:

- who the customer is and where they already talk (which apps, which communities);
- how money comes in (Stripe payment links, invoices in Xero, a Square store...);
- the three to five jobs that repeat every week.

Tell the founder what you found in five lines, with the links you used.

## 2. Pick the roles and their apps

- Two to five roles. A role is a permission class, not a person: "support", "ops lead", "marketer".
- Each role's `apps` are Arcade toolkit names, spelled as Arcade spells them (`Gmail`, `Stripe`,
  `X`, `GoogleSheets`, `HubspotCrmApi`). Check each one with `arcade_search_tools` before you use it.
- `ships` lists the apps where that role may take actions others see: send, post, pay, delete.
  Most roles ship nothing. One role usually owns the money.
- The `lead` is the role the founder's main session plays.
- `limits` caps money per call and per day on the tools listed under `money`, in that tool's own
  unit (Stripe amounts are cents). Set a company default and a higher one for the money role.
- `tasks` are the first jobs, each assigned to a role; `every: "weekdays 09:00"` makes one recur.

## 3. Save the draft

Call `arcade_draft_company` with the spec. If it returns `the spec needs fixing`, fix exactly
what it names and call it again. When it returns a draft path, show the founder:

- the roles, their apps and where each may ship;
- the command it returned, and the four settings to choose from:
  - `yolo`: every tool, no approval cards. Receipts, money limits and `/arcade halt` still hold.
  - `founder`: every tool; anything that ships waits for the founder's card.
  - `roles`: each role gets only its apps (the default).
  - `strict`: roles, with every tool pinned by name.

Never run `/arcade found` or `/arcade mode` yourself, and never suggest turning Hermes approvals off:
the settings above are how the founder trades speed for control.
