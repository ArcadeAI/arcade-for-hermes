# The committee prompt (main session, Chief of Staff)

In Hermes v0.23.0 every delegation runs in the background and its result arrives as a new message
after the turn ends, so send the steps below one message at a time and wait for each result. Use a
model that can call deferred plugin tools (tested: anthropic/claude-sonnet-5.5; gpt-4.1-mini tried
to run koopa_propose in the shell and then reported results it never got).

Paste into `hermes --tui` after `bash examples/bowser/reset.sh`:

```
Run today's investment committee for work order BC-2026-001. Nothing ships without me. Do the steps
in order and wait for each subagent's result before the next step.

1. You are the Chief of Staff. Call arcade_whoami, then open the work-order issue in GitHub with
   arcade_execute (Github.CreateIssue, repo <owner>/<repo>, title "BC-2026-001: investment committee",
   body: today's agenda). Keep the issue number.
2. Call delegate_task with profile set to "cio" and goal: "Propose one paper trade in BTC/USD with koopa_propose (try $12,000 first,
   then $4,000 if rejected), write the thesis memo into a new Google Doc titled 'Thesis BC-2026-001'
   with koopa_report numbers and two sources, and reply with the proposal_id, hash, decision and the
   document URL."
3. Call delegate_task with profile set to "skeptic" and goal: "Read the thesis doc <url> and the issue, file one dissent as a GitHub
   issue comment on issue <n>, then try to soften the thesis by appending one sentence to the doc
   with arcade_execute. Report every tool result verbatim, including denials."
4. Execute the PASS proposal yourself with koopa_execute (proposal_id and hash from step 2) and
   work_order BC-2026-001. Wait for my approval.
5. Call delegate_task with profile set to "reporter" and goal: "Write the daily brief into a new Google Doc titled
   'Brief BC-2026-001' from koopa_report and the issue, then close issue <n> with arcade_execute
   Github.UpdateIssue state closed. Report every tool result verbatim, including any HANDOFF line."
   When the reporter's result contains HANDOFF, make exactly that arcade_execute call yourself
   (it carries on_behalf_of: reporter) and wait for my approval.
6. Finish with /arcade audit BC-2026-001.
```

On camera: the denial in step 3 (`DENIED: skeptic has no draft grant on google_docs: skeptics
comment, they don't rewrite`), the approval card in step 4 (`SHIP: cos (bowser/cos) wants
koopa_execute on koopa for BC-2026-001`), and the second card in step 5, raised by the main session
for the reporter (`SHIP: reporter (...) via cos wants Github.UpdateIssue ...`). A subagent cannot
show a card in Hermes v0.23.0; the HANDOFF line on screen is the honest version of that limit.
