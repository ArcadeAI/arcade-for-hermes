"""Tool schemas: what the model reads to decide when to call each Arcade tool."""

ARCADE_SEARCH_TOOLS = {
    "name": "arcade_search_tools",
    "description": (
        "List Arcade tools this agent could call, with each tool's name, description and the verb the "
        "policy assigns it (look, draft, ship, or denied). Use it to find the exact Arcade tool name "
        "before calling arcade_execute. Executes nothing and changes nothing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words to match against tool names and descriptions (e.g. 'issue', 'document')."},
            "toolkit": {"type": "string", "description": "Restrict to one toolkit from the policy (e.g. 'github', 'google_docs'). Default: every toolkit in the policy."},
            "limit": {"type": "integer", "description": "Maximum tools to return (default 25, max 100)."},
        },
        "required": [],
    },
}

ARCADE_AUTHORIZE = {
    "name": "arcade_authorize",
    "description": (
        "Get the sign-in link that connects this role's Arcade principal to an app (toolkit). Call it when "
        "arcade_execute returns authorization_required, show the link to the human, then retry after they "
        "consent. Never opens a browser and never escalates a grant by itself."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "toolkit": {"type": "string", "description": "Toolkit to connect (e.g. 'github', 'google_docs')."},
            "tool": {"type": "string", "description": "Optional exact Arcade tool name to authorize instead of the toolkit's default."},
        },
        "required": ["toolkit"],
    },
}

ARCADE_EXECUTE = {
    "name": "arcade_execute",
    "description": (
        "Run one Arcade tool as this role's own Arcade principal, under the look/draft/ship policy. "
        "look and draft calls run and leave a receipt; ship calls (anything others see, or that moves money) "
        "wait in Hermes's approval gate for the human; off-policy calls are denied before Arcade is called. "
        "Always pass the work_order ID you are working on. If the result is authorization_required, "
        "call arcade_authorize and show the link. Inside a subagent a ship call returns HANDOFF instead of running: "
        "report that line back; the main session re-issues it with on_behalf_of."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "description": "Exact Arcade tool name, e.g. 'Github.CreateIssue' (find it with arcade_search_tools)."},
            "input": {"type": "object", "description": "The tool's input parameters, as Arcade documents them."},
            "work_order": {"type": "string", "description": "Work-order ID this call belongs to (e.g. 'BC-2026-001'). Appears on the receipt and the approval card."},
            "on_behalf_of": {"type": "string", "description": "Main session only: the role whose ship action a subagent handed back (its result said HANDOFF). Copy the call from the HANDOFF line exactly. The approval card names both roles."},
        },
        "required": ["tool", "input"],
    },
}

ARCADE_WHOAMI = {
    "name": "arcade_whoami",
    "description": (
        "Show which role this agent plays, its Arcade principal (user_id), what the policy lets it look at, "
        "draft and ship per toolkit, and optionally which apps are already connected for it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "check_connections": {"type": "boolean", "description": "Also ask Arcade which toolkits are connected for this principal (one request per toolkit). Default false."},
        },
        "required": [],
    },
}

ARCADE_DRAFT_COMPANY = {
    "name": "arcade_draft_company",
    "description": (
        "Save a company the founder described as a draft spec: roles, the Arcade toolkits each role uses, where each "
        "role may ship, money limits and the first tasks. Validates every toolkit against Arcade's catalog and returns "
        "the draft's path and the command the founder runs to start it. This never starts the company or changes any "
        "permission: only the founder's /arcade found does. Use the found-a-company skill to research first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "description": ("{name, pitch, lead: <role>, limits?: {per_call, per_day}, roles: {<role>: {title, does, apps: "
                                "[Arcade toolkit names, e.g. Gmail, Stripe, X], ships?: [subset of apps], limits?}}, money?: "
                                "[{tool, amount: <input field holding the amount>}], tasks: [{title, role, body, every?: "
                                "'weekdays 09:00'}]}"),
            },
        },
        "required": ["spec"],
    },
}

ALL = (ARCADE_SEARCH_TOOLS, ARCADE_AUTHORIZE, ARCADE_EXECUTE, ARCADE_WHOAMI, ARCADE_DRAFT_COMPANY)
