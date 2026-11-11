# Arcade for Hermes

Start a company of Hermes agents that works in real tools: any kind of company, any Arcade tool, or your own custom MCP servers, with every action governed.

> Built at Arcade by Thierry Damiba for the Hermes Agent Plugin Hackathon. It runs on Arcade's
> public API and Arcade's official Hermes plugin.

A native [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that gives each Hermes
agent its own governed identity in your business apps through [Arcade](https://arcade.dev):

- **One Arcade principal per role.** The profile a Hermes agent runs as (`cio`, `skeptic`,
  `reporter`) becomes its Arcade `user_id` (`bowser/cio`). Apps see one person; Arcade, the policy
  and the receipts see the role.
- **look / draft / ship.** A policy file decides, per role and tool call, whether the call reads,
  drafts, or ships. look and draft run with a receipt. ship waits in Hermes's own approval gate in
  the main session (a subagent hands its ship actions back, see Approvals). Everything else is
  denied before Arcade is called.
- **A receipt for every call.** Actor, principal, tool, verb, decision, approver, work order and the
  artifact's URL, one JSON line each. `/arcade audit BC-2026-001` lists them.

It is built for the Nous Research Hermes Agent Plugin Hackathon and tested against Hermes v0.23.0.

## For reviewers

What this plugin does that a prompt or a skill cannot: it decides every Arcade call in code, in
`pre_tool_call`, before the call leaves Hermes. The model cannot talk its way past a cap, a halt or
a denied tool, and every decision lands in a receipt the model did not write.

| Criterion | Evidence |
|---|---|
| Usefulness | One command founds a company: a Hermes profile per role, the Arcade apps each role may use (8,700+ tools), a policy and a kanban board. Roles act in real apps (Gmail, GitHub, Docs, Alpaca paper trading) under their own Arcade identity. |
| Reliability | 218 offline tests; `hermes plugins validate --install-deps` passes (security scan: safe); `doctor --ci` OK (5 tools, 8 hooks). Default deny: a tool the policy does not name never reaches Arcade. Every decision is written as a receipt. |
| Polish | Ship actions use Hermes's own approval card; the model is told when the founder approved (`transform_tool_result`); `/arcade halt`, `/arcade mode`, `/arcade audit`; a live Floor and gate log in the terminal. |
| Creativity | Agents get badges, not keys: per-role identity in real apps, a look/draft/ship verb for every one of Arcade's tools, and a dial (founder, roles, yolo) where even yolo keeps caps and halt. |

Hermes surfaces used: `register_tool` (5), hooks (`pre_tool_call`, `post_tool_call`,
`post_approval_response`, `transform_tool_result`, `pre_api_request`, `post_api_request`,
`api_request_error`, `on_interim_message`), a slash command, bundled skills, kanban and cron, and a
dashboard tab. Disclosures are below under "Disclosures".

## Start an AI company

The plugin is also a starter kit. Describe a business, or pick a template, and Hermes sets it up as
a company: a role per job, a Hermes profile per role, the Arcade apps each role may use, and a task
board with the first work on it.

1. **Type the idea.** "A paid newsletter and community for indie game developers." The
   `found-a-company` skill has the agent research it with Arcade's search tools and pick roles and
   apps.
2. **It drafts the company.** `arcade_draft_company` checks every app against Arcade's catalog and
   saves a draft. The agent cannot start it: founding rewrites permissions, so only you do that.
3. **You start it.** `/arcade found <template or draft> [setting]` writes the policy, makes the
   role profiles with their own SOUL.md, routes subagents to them, puts the first tasks on a
   `hermes kanban` board and schedules the recurring ones with `hermes cron`.
4. **You sign in.** `/arcade connect` gives one link per app (per role, with your own OAuth apps).
5. **It runs.** `hermes kanban --board <company> daemon` works the board, each task as its role.
6. **Every Arcade tool is in reach.** All 8,715 tools in Arcade's catalog (131 toolkits, counted
   2026-11-08) have a verb, so a role can be given any app by name.

Templates (`/arcade templates` lists them):

| Template | Apps | Gateway |
|---|---|---|
| `coo` | Gmail, Calendar, Docs, Slack, Notion: one agent | Arcade's official |
| `software-startup` | GitHub, Linear, Vercel, PagerDuty, PostHog, Slack | Arcade's official |
| `shirt-shop` | Stripe, Gmail, Sheets, X, Reddit | Arcade's official |
| `trading-desk` | ArcadeAlpaca (your own toolkit), GitHub, Docs, Google News and Finance | your own |

Founding checks each app against the 90 apps on Arcade's official gateway
(`data/arcade_gateway_apps.json`, read 2026-11-08 with `Arcade_ListApps`) and warns about the rest.
A spec with `gateway: own` runs on a project gateway you deployed, which can serve any toolkit,
your own included. Every role profile gets the lead's gateway entries and is linked to the lead's
sign-in, so one sign-in runs the company.

### The dial: from yolo to strict

`/arcade mode <setting>` moves a running company between four settings. Each one is an ordinary
policy file you can read and diff.

| Setting | Who may use what | Ship actions |
|---|---|---|
| `yolo` | every role, every tool | run without a card, under a mandate written in the policy. Receipts, money limits and `/arcade halt` still hold |
| `founder` | every role, every tool | wait for your card |
| `roles` | each role, only its own apps; it ships only where the spec says | wait for your card |
| `strict` | as `roles`, with every tool pinned by name (a tool Arcade adds later is denied) plus your own input-level rules | wait for your card |

`yolo` is never Hermes's approvals-off switch: the plugin's gate still decides every call, and the
setting is one line per role (`approval: mandate`) you can see in the policy. You can also mix: a
marketer on `mandate` and the money role on `card`.

### How a tool gets its verb

`verbs.py` reads two things and keeps the stricter answer: Arcade's own behavior metadata
(`read_only`, `destructive`, `operations`), which about a fifth of the catalog carries, and the
tool's name (Get and List read, Create and Update draft, Send, Delete and Pay ship). A money or
exposure word anywhere in the name (Refund, Payment, Invite, Permission, Webhook) makes it ship.
Whatever neither can place ships, so an unknown tool goes to your card. `scripts/build_verbs.py`
rebuilds the snapshot in `data/arcade_verbs.json`; a policy turns it on with `catalog: true`, and
explicit rules still win.

What was checked, 2026-11-08: the full flow ran live in a fresh Hermes home. An idea was
researched with GoogleSearch (cited sources), drafted, founded at `founder` (two role profiles,
five board tasks), and a role agent saw exactly its grants (`Stripe.CreateRefund`: ship, not
allowed for support). Not yet run: a board daemon working tasks end to end, and whether a card
reaches your phone from a kanban worker (under `yolo` no card is needed).

## How it relates to Arcade's existing plugin

Arcade already publishes a portable Agent Plugins package (the `arcade-plugin` repository in the
ArcadeAI GitHub organization, see the [Arcade plugin guide](https://docs.arcade.dev)). It points your
client at the `api.arcade.dev/mcp/arcade` gateway and ships skills and commands for Cursor, Claude
Code, Copilot and others. It signs *you* in, once, and every tool runs as you. Use it when one
identity is what you want.

Arcade for Hermes is the native Hermes layer the portable package cannot be: per-role principals
through `arcadepy`, a `pre_tool_call` policy, escalation into Hermes's approval gate, and receipts.
Hermes's own Connectors are the same idea as the portable package: the founder's keys. This plugin
issues the employees' badges.

## Install

Requirements: Hermes `>=0.22.5` (tested on v0.23.0), an Arcade API key, and, for per-role
identity, the official `advanced-delegation` plugin.

```bash
hermes plugins install ArcadeAI/arcade-for-hermes --enable
hermes plugins install advanced-delegation --enable
```

Then:

1. Put `ARCADE_API_KEY` in the `.env` of **every profile that will act**: the main profile and each
   role profile (`hermes config env-path` prints the path for the current profile). The plugin
   reads it through Hermes's secret scope, so a routed subagent reads its own profile's key.
2. Enable the plugin in every role profile too. Hermes keeps one plugin set and one tool registry
   per profile, so a subagent routed to `cio` only sees `arcade_*` if `cio` has the plugin enabled:
   `HERMES_HOME=~/.hermes/profiles/cio hermes plugins enable arcade-for-hermes`.
3. Copy `policy.example.yaml` to `~/.hermes/arcade/policy.yaml` and edit the roles. The bundled
   example is used until you do, and `/arcade status` says so.
4. Route subagents to profiles: `hermes delegation config`, pick **Profile routes**, tick the role
   profiles. This writes `delegation.backend: profile_routes` to the main profile's config. Plain
   `delegate_task` has no profile choice; without this step every subagent runs as the main
   session's role.
5. Pick an identity mode. Arcade checks that the person who clicks a consent link is the user the
   flow was started for:
   - **Per-role principals** (`bowser/cio`, the default). Arcade's own OAuth apps for GitHub and
     Google only accept the Arcade account signed into the browser, and Arcade's docs say flows on
     those default apps "always fall back to the Arcade user verifier, even if you have a custom
     verifier route configured". So per-role principals need **your own OAuth app credentials** in
     the Arcade project for each provider (Connections, OAuth providers), plus the project's
     **User verification** set to **Custom user verifier** pointing at `http://127.0.0.1:8765`.
     `/arcade connect` starts that verifier (`verifier_host`, `verifier_port`,
     `verifier_public_url` change it). After the app's sign-in, Arcade sends you to the verifier, you
     pick the role you consented as, and Arcade finishes. If Hermes runs on another machine, run
     `scripts/arcade_verifier.py` on the laptop with the browser.
   - **One shared principal** (no OAuth apps of your own). Add `shared_principal: you@example.com`
     (your Arcade account) to the policy. Every role acts as you in Arcade; grants, approvals and
     receipts still separate the roles, and `/arcade status` warns that Arcade sees one user.
6. `/arcade connect` prints the sign-in links: one per role per app with per-role principals
   (four roles and two apps is eight), one per app with a shared principal. Re-run it after
   consenting; it is safe to repeat. GitHub's app only reaches private repos it is installed on
   (github.com/settings/installations); a private repo it cannot see answers `Not Found`.

## Commands

| | |
|---|---|
| `/arcade status` | roles, principals, grants per toolkit, whether the key is present, which delegation backend is active, and a warning for every approval bypass that is on |
| `/arcade audit [work_order]` | receipts, newest first |
| `/arcade connect [toolkit]` | sign-in links for every role and toolkit |
| `/arcade halt [reason]` / `/arcade resume` | the kill switch: every draft and ship denied except exits, then back |
| `/arcade templates` | the starter companies |
| `/arcade found <template or draft> [setting]` | start a company: policy, a profile per role, delegation routes, the board, schedules |
| `/arcade mode [setting]` | show or move the dial: `yolo`, `founder`, `roles`, `strict` |

The same run from a terminal as `hermes arcade status|audit|connect|halt|resume|templates|found|mode`.

## Tools the model gets

| Tool | Does |
|---|---|
| `arcade_search_tools(query?, toolkit?)` | lists Arcade tools with the verb the policy gives each one; executes nothing |
| `arcade_authorize(toolkit)` | returns this role's sign-in link; never opens it |
| `arcade_execute(tool, input, work_order?, on_behalf_of?)` | runs one Arcade tool as this role's principal under the policy; returns the result plus a receipt. `on_behalf_of` is main-session only, for a ship action a subagent handed back |
| `arcade_whoami()` | role, principal, grants, optional connection check |
| `arcade_draft_company(spec)` | validates a company spec against Arcade's catalog and saves it as a draft; never starts it |

`arcade_execute` re-checks the policy itself and refuses anything denied, and refuses a ship action
that did not pass through the approval gate, so the hook is not the only control.

## The policy file

```yaml
version: 1
default: deny                       # the only accepted value
principal_prefix: bowser            # user_id = "bowser/<role>"
toolkits:
  github: [Github]                  # canonical name -> prefixes seen in Arcade tool names
  google_docs: [GoogleDocs]
connect: {github: Github.WhoAmI, google_docs: GoogleDocs.WhoAmI}
profile_roles: {default: cos, cio: cio, skeptic: skeptic, reporter: reporter}
rules:                              # first match wins; a rule may match on input
  - {tool: Github.ListIssues, verb: look}
  - {tool: Github.UpdateIssue, verb: ship, input: {state: closed}}
  - {tool: Github.UpdateIssue, verb: draft}
  - {tool: koopa_execute, verb: ship, toolkit: koopa}   # a local Hermes tool, governed too
roles:
  skeptic:
    grants:
      - {toolkit: github, verbs: [look, draft]}
      - {toolkit: google_docs, verbs: [look]}
    deny_reasons: {google_docs.draft: skeptics comment, they don't rewrite}
```

- Tool names are Arcade's own. `arcade_search_tools` lists them; never guess.
- A general tool can be two verbs: `Github.UpdateIssue` is ship when `state: closed` and draft
  otherwise. `GoogleDocs.EditDocument` is look when it carries no `requests`.
- A non-Arcade Hermes tool is governed when a rule names it with an explicit `toolkit`. Nothing
  about any particular local tool lives in plugin code; the demo's Koopa tools live only in
  `examples/bowser/policy.yaml`.
- **Ownership.** A draft grant may carry `owns:` input matchers (`{document_id: thesis-*}`). When
  it does, the role may only draft matching artifacts. When it does not, ownership is **not
  enforced**: the CIO and the Reporter in the example can both edit any Google Doc they are
  allowed to draft. `/arcade status` marks each grant `[owns]` or not.
- An unknown role, an unlisted tool, an undeclared toolkit or a missing grant is denied. A
  profile the policy does not map to a role gets nothing.

## Agents that move money

People who trade through agents keep asking for the same things (see the open requests on Alpaca's
MCP server for a pre-trade check, order limits and approvals). The policy covers them for any Arcade
tool that moves money, not one broker:

- **The agent that proposes is not the agent that executes.** Grants are per role; in the demo the
  CIO proposes, only the Chief of Staff can execute, and only on the founder's card.
- **Limits per role.** A rule names the input that carries the amount (`amount: notional`), a role
  sets `limits: {per_call, per_day}`. Over the limit is denied before any card; an amount the policy
  cannot read is denied too. Today's total comes from the receipts, so it survives restarts.
- **A kill switch.** `/arcade halt [reason]`, from the terminal or a text, denies every draft and
  ship action until `/arcade resume`. Reads keep working.
- **Exits are never blocked.** Rules marked `exit: true` (close a position, cancel an order) still go
  to the card while halted.
- **No broker key in the agent.** The broker's keys are secrets in your Arcade project; Hermes holds
  only `ARCADE_API_KEY`, and an agent that dumps its environment finds no broker credential.
- **Destructive tools are named, not guessed.** Every tool is look, draft or ship by rule, and an
  unlisted tool is denied, so `CancelAllOrders` can never pass as a read.

Not covered: limits are checked per call against receipts, so two approvals answered at the same
instant can both pass the daily check; there is no loss-based halt (the policy sees orders, not
P&L); and on-chain wallets are a different job (Hermes's MetaMask Wallet plugin does approvals and a
rolling spend limit for EVM wallets).

## Approvals, honestly

- A ship action returns `{"action": "approve", "rule_key": <per-action hash>}` from
  `pre_tool_call`. The key hashes role, tool, input and work order, so a "session" or "always"
  answer covers that exact action only, never the next one.
- Denial, timeout, cancellation and gate errors all block the call. The receipt records the
  choice and the surface (`once@gateway`, `deny@cli`, `timeout`). `hermes --tui` reports itself as
  `gateway`.
- Where nobody can answer (cron, `hermes chat -q`, a webhook platform) Hermes fails closed and the
  receipt says `NEEDS_HUMAN`. In a cron run the plugin blocks before the gate.
- **Subagents hand ship actions back.** Hermes v0.23.0 runs every model-dispatched `delegate_task`
  in the background, and a background child's approval callback denies with no card
  (`delegation.subagent_auto_approve` is false by default). Seen in `hermes --tui`: a reporter's
  close was denied twice with no card. So inside a routed child, a ship action the role is granted
  is blocked at once with a `HANDOFF` line that spells out the exact call. The main session
  re-issues it with `on_behalf_of: <role>`; the card reads `SHIP: reporter (...) via cos wants ...`,
  the policy checks the reporter's grant, the call runs as the reporter's principal, and the receipt
  records `role: reporter, via: cos`. `on_behalf_of` is refused inside a subagent, for unknown
  roles, and for anything but a ship action, so it never runs anything without a human.
- **Bypasses this plugin never sets, and warns about:** `delegation.subagent_auto_approve: true`
  approves subagent ship actions with no human; `approvals.mode: off`, `--yolo`,
  `HERMES_YOLO_MODE` and a gateway `/yolo` bypass the gate entirely. `/arcade status` lists the
  ones visible from a plugin (config and process env); a session `/yolo` toggle is not visible to
  plugins.

## Disclosures (catalog rules 11, 12, 13)

- **Network.** Every `arcade_*` call and `/arcade connect` talk to `api.arcade.dev` (or
  `ARCADE_BASE_URL`) with your `ARCADE_API_KEY`. App OAuth tokens are stored by Arcade and never
  reach Hermes. The plugin makes no other network calls and sends no telemetry.
- **Credentials.** `ARCADE_API_KEY` and `ARCADE_BASE_URL` are read with
  `agent.secret_scope.get_secret`. No `.env`, `auth.json`, keychain or other store is read.
- **Approvals.** Ship actions go through Hermes's gate via the documented `pre_tool_call`
  directive. The plugin never auto-approves, never changes approval settings, and never opens a
  browser.
- **Files written.** Receipts at `<launch HERMES_HOME>/plugin-data/arcade-for-hermes/receipts.jsonl`
  (configurable with the `receipts_path` setting). Inputs are summarized; strings are cut at 80
  characters and credential-looking keys are redacted. No document bodies, no tokens, no sign-in
  links. Beside it, `activity.jsonl` feeds the Floor (below): who is thinking, the model's first
  interim sentence before a tool call (cut to 96 characters, links, addresses, phone numbers and
  long tokens scrubbed), and which local tools were used. It is trimmed to the last 400 lines and is
  a view, not a record.
- **Dashboard.** The Floor tab reads those two files through Hermes's local dashboard API
  (`dashboard/plugin_api.py`). It makes no network calls and never shows principals, session keys,
  URLs or task ids.
- **Dependencies.** One: `arcadepy>=1.10.0,<1.11`. Pure Python, nothing downloaded at runtime,
  no self-update.

## Identity, stated plainly

All principals are authorized against the founder's own app accounts (user-delegated OAuth), so
GitHub and Google see the founder while Arcade, the policy and the receipts see the role. One
consent per role per app, and your own OAuth apps in the Arcade project. With `shared_principal`,
Arcade sees the founder too and only the policy and receipts see the role. All principals share one
`ARCADE_API_KEY`, and the plugin chooses the `user_id`, so the role boundary is as strong as the
plugin and the policy, not a separate Arcade credential per role.

## The demo: Bowser Capital

`examples/bowser/` is the test harness, not the product: a one-founder paper-trading firm whose
CIO, Skeptic and Reporter are Hermes profiles. It holds the demo policy (with the Koopa grants),
the three role `SOUL.md` files, the committee prompt, a reset script (`ARCADE_SHARED_PRINCIPAL=you@example.com`
adds `shared_principal` to the installed policy), and **Koopa**, a separate
three-tool Hermes plugin on fixture prices (`koopa_propose`, `koopa_execute`, `koopa_report`;
PAPER MODE on every line, MOCK on every fill, no broker, no network by default). `koopa_execute` is a ship
action in the policy, granted to the Chief of Staff in the main session, so it goes through the same
gate as closing an issue.

Optional broker: with `KOOPA_BROKER=alpaca` in the main profile's `.env`, an approved
`koopa_execute` places a market order on an Alpaca **paper** account through your own Arcade-hosted
`ArcadeAlpaca` toolkit (deployed to the same Arcade project as the plugin's key, with the Alpaca
paper keys set as project secrets). It first calls `ArcadeAlpaca.GetAccount` and refuses unless the
account reports the paper endpoint; the proposal's ID and hash are the order's idempotency key, so
a retry cannot place a second order. The order tools are ship actions that no role holds: the only
way to place an order is the founder's Allow on the `koopa_execute` card.

The swarm: `python examples/bowser/swarm.py 100` turns the firm into 100 Hermes profiles (84
analysts split across Koopa's allow-list, 12 skeptics, 3 risk officers, a reporter), each on
`anthropic/claude-haiku-5.5` by default, and lists them under `profile_routes`. The policy does
not grow: wildcard `profile_roles` (`"analyst-*": analyst`) map every profile onto four roles, so a
hundred agents hold exactly four sets of grants, every ship action still comes back to one card,
and `/arcade audit` names the profile behind each receipt (`analyst (analyst-042)`).

```bash
bash examples/bowser/reset.sh --install   # profiles, souls, both plugins enabled per profile, policy
bash examples/bowser/reset.sh             # between takes: fixtures, receipts
```

## The Floor

An 8-bit view of the firm, drawn only from receipts and the activity feed: each role is a little
worker who walks to the Arcade kiosk for a tool call, carries a memo, gets stopped with a red
DENIED, or waits at the gate for the founder's card. It is a tab in `hermes dashboard`, and a terminal
build of the same code (`node dashboard/floor_term.js`, live or `--replay BC-2026-003`) for Rex or
any 24-bit terminal.

## The Arena (examples/arena)

A stress test of the policy, not a trading product. Two desks share one founder's mandate on live
Alpaca crypto quotes with **paper fills** (no broker orders; fills at the quoted bid and ask, a 25
bps fee that is an assumption). The red desk is a nine-seat quant firm, every seat a Hermes profile
mapped to its own role: Data, two Researchers and a Quant Dev reach Arcade's catalog (E2B for
backtests, Google News and Search), the PM funds one thesis, only Execution may trade, Risk and
Compliance post sign-offs, IR writes the LP letter. The blue desk can run with no Arcade at all, as
a control: the same arena tools with no policy hook, and a witness that records what the policy
*would* have blocked. Every model call is metered (Hermes's `post_api_request` usage, priced by Hermes), and the
score is net of the desk's own model bill: the firm's standing thesis is that it has to make more
than it costs to think.

```bash
python examples/arena/arena.py setup
python examples/arena/arena.py run --crew quant --no-arcade blue --minutes 10 --want chaos
python examples/arena/arena.py board        # the referee's view; the Floor shows the rooms
```

## Development

```bash
hermes plugins validate ./ --install-deps     # the catalog CI gate
hermes plugins doctor ./ --ci
python -m pytest -q                            # offline: policy, receipts, hooks, handlers, identity
bash scripts/local_spike.sh                    # the checks that need a person: cards, consent, TUI
```

Tests need no keys and no network. They load the directory as a package the way Hermes does.

## Security

Report security issues to security@arcade.dev, not in a public issue. See [SECURITY.md](SECURITY.md).

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
