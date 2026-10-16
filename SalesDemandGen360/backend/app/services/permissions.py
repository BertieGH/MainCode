"""What each role may do, and which part of the API each route belongs to.

**Modules** are the screens a person works in. Each role has `none`, `view` or
`edit` on each — a GET needs `view`, anything else needs `edit`. Create and
edit are one level because config is versioned here: saving already creates a
new version (`docs/17`).

**Actions** are the few operations that cost money or reach a customer. They
are switched per role on top of the module level, so a Marketing user can
edit drafts all day without being able to send one.

**Admin** has everything, always, and is not in the grid at all — so no grid,
however it is edited, can lock the last admin out of fixing it.

**Every route must match a rule.** One that does not is admin-only: a route
added next month and forgotten here fails closed rather than open, and
`test_permissions` names it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VIEW, EDIT, NONE = "view", "edit", "none"
LEVELS = (NONE, VIEW, EDIT)

#: key → label, in the order the Roles screen shows them.
MODULES: dict[str, str] = {
    "dashboard": "Dashboard, Cost & health",
    "lists": "Account Lists & research",
    "queues": "Campaign Queues",
    "outreach": "Outreach — strategy & drafts",
    "prep": "Sales Prep",
    "models_prompts": "Model & Prompts config",
    "sources_signals": "Sources & signals",
    "content": "Services & proof, ICP, Writing samples",
    "scoring": "Weights & scoring",
    "rules_cadences": "Sales rules & Cadences",
}

#: Admin-only modules. Not in the grid: nobody can be given them by mistake.
ADMIN_MODULES: dict[str, str] = {
    "api_config": "API config (keys)",
    "users": "Users & Roles",
}

ACTIONS: dict[str, str] = {
    "approve_send": "Approve & send to LGM",
    "paid_research": "Run paid research",
    "delete_campaign": "Delete a campaign",
}

#: Readable by anyone signed in: the facts every screen needs to draw itself
#: (is the installation set up, which providers exist, which cadences exist).
SHARED = "shared"

#: Column order on Settings › Roles: the operators, then the two business roles,
#: DemandGen before Marketing.
ROLES_IN_GRID = ("aiops", "demandgen", "marketing")

#: The grid agreed in chat on 2026-10-15 and drawn in `mockups/user-access.html`.
#: Seeded as version 1; edited afterwards on Settings › Roles.
DEFAULT_GRID: dict = {
    "modules": {
        "aiops": {
            "dashboard": EDIT, "lists": VIEW, "queues": VIEW, "outreach": VIEW, "prep": VIEW,
            "models_prompts": EDIT, "sources_signals": EDIT, "content": VIEW, "scoring": EDIT,
            "rules_cadences": VIEW,
        },
        "marketing": {
            "dashboard": VIEW, "lists": EDIT, "queues": VIEW, "outreach": EDIT, "prep": EDIT,
            "models_prompts": VIEW, "sources_signals": VIEW, "content": EDIT, "scoring": EDIT,
            "rules_cadences": VIEW,
        },
        "demandgen": {
            "dashboard": VIEW, "lists": EDIT, "queues": EDIT, "outreach": EDIT, "prep": EDIT,
            "models_prompts": VIEW, "sources_signals": VIEW, "content": VIEW, "scoring": VIEW,
            "rules_cadences": EDIT,
        },
    },
    "actions": {
        "aiops": ["paid_research"],
        "marketing": ["paid_research"],
        "demandgen": ["approve_send", "paid_research", "delete_campaign"],
    },
}


# --------------------------------------------------------------------------
# which route is which
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    methods: frozenset[str] | None  # None = any
    pattern: re.Pattern[str]
    module: str
    action: str | None = None


def _r(methods: str | None, path: str, module: str, action: str | None = None) -> Rule:
    """`path` is the route template after `/api`, e.g. `campaigns/{id}/execute`.

    `{x}` matches one segment and a trailing `/**` matches anything below.
    """
    rx = re.escape(path).replace(r"/\*\*", r"(/.*)?")
    rx = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", rx)
    ms = frozenset(methods.split(",")) if methods else None
    return Rule(ms, re.compile(rf"^/api/{rx}$"), module, action)


#: First match wins, so specific rules sit above the general ones they carve
#: out of. Paths are route templates, matched against the route FastAPI chose
#: — never the raw URL, which a crafted path could bend.
RULES: tuple[Rule, ...] = (
    # --- readable by every signed-in user ---
    _r("GET", "config/readiness", SHARED),
    _r("GET", "config/providers", SHARED),
    _r("GET", "config/mode", SHARED),
    _r("GET", "config/query-families", SHARED),
    _r("GET", "cadence-shapes", SHARED),
    _r("GET", "lgm/campaigns", SHARED),

    # --- admin only ---
    _r(None, "users/**", "users"),
    _r(None, "users", "users"),
    _r(None, "roles/**", "users"),
    _r(None, "roles", "users"),
    _r(None, "config/credentials/**", "api_config"),
    _r(None, "config/credentials", "api_config"),
    _r(None, "config/enrichment", "api_config"),
    _r(None, "config/mode", "api_config"),
    _r(None, "lgm/inbox-webhooks", "api_config"),

    # --- dashboard ---
    _r(None, "monitoring", "dashboard"),
    _r(None, "config/llm/spend", "dashboard"),

    # --- lists & research. What spends credits or tokens is an action. ---
    _r("POST", "lists/{id}/run-research", "lists", "paid_research"),
    _r("POST", "accounts/{id}/run-research", "lists", "paid_research"),
    _r("POST", "lists/{id}/find-contacts", "lists", "paid_research"),
    _r("POST", "lists/{id}/verify-contacts", "lists", "paid_research"),
    _r("POST", "lists/{id}/qualify", "lists", "paid_research"),
    _r("POST", "lists/{id}/check-companies", "lists", "paid_research"),
    _r("POST", "lists/from-apollo", "lists", "paid_research"),
    _r(None, "lists/**", "lists"),
    _r(None, "lists", "lists"),
    _r(None, "accounts/**", "lists"),
    _r(None, "accounts", "lists"),
    _r(None, "contacts/**", "lists"),

    # --- queues. Promoting one makes a campaign, and is queue work. ---
    _r(None, "queues/**", "queues"),
    _r(None, "queues", "queues"),
    _r("POST", "campaigns", "queues"),

    # --- outreach. Approving and sending are the gate, not the module. ---
    _r("POST", "campaigns/{id}/execute", "outreach", "approve_send"),
    _r("POST", "campaigns/{id}/approval/accept-sample", "outreach", "approve_send"),
    _r("POST", "sequences/{id}/decision", "outreach", "approve_send"),
    _r("DELETE", "campaigns/{id}", "outreach", "delete_campaign"),
    _r(None, "campaigns/**", "outreach"),
    _r(None, "campaigns", "outreach"),
    _r(None, "sequences/**", "outreach"),

    # --- sales prep ---
    _r(None, "prep/**", "prep"),
    _r(None, "prep", "prep"),

    # --- settings ---
    _r(None, "config/llm/**", "models_prompts"),
    _r(None, "config/llm", "models_prompts"),
    _r(None, "config/model-availability", "models_prompts"),
    _r(None, "config/prompts/**", "models_prompts"),
    _r(None, "config/prompts", "models_prompts"),
    _r(None, "config/research-sources/**", "sources_signals"),
    _r(None, "config/research-sources", "sources_signals"),
    _r(None, "config/research-settings", "sources_signals"),
    _r(None, "config/signal-types/**", "sources_signals"),
    _r(None, "config/signal-types", "sources_signals"),
    _r(None, "config/services/**", "content"),
    _r(None, "config/services", "content"),
    _r(None, "config/proof-points/**", "content"),
    _r(None, "config/proof-points", "content"),
    _r(None, "config/icp-profiles/**", "content"),
    _r(None, "config/icp-profiles", "content"),
    _r(None, "config/writing-samples/**", "content"),
    _r(None, "config/writing-samples", "content"),
    _r(None, "config/org-profile/**", "content"),
    _r(None, "config/org-profile", "content"),
    _r(None, "config/scoring/**", "scoring"),
    _r(None, "config/scoring", "scoring"),
    _r(None, "config/sales-rules/**", "rules_cadences"),
    _r(None, "config/sales-rules", "rules_cadences"),
    _r(None, "cadence-shapes/**", "rules_cadences"),
    _r(None, "cadence-shapes", "rules_cadences"),
)


def rule_for(method: str, path: str) -> Rule | None:
    method = method.upper()
    for rule in RULES:
        if (rule.methods is None or method in rule.methods) and rule.pattern.match(path):
            return rule
    return None


# --------------------------------------------------------------------------
# deciding
# --------------------------------------------------------------------------
def level_needed(method: str) -> str:
    return VIEW if method.upper() in ("GET", "HEAD", "OPTIONS") else EDIT


def effective(grid: dict, role: str) -> dict:
    """What a role can do: every module with a level, and its actions.

    Admin's answer is computed, never read from the grid.
    """
    if role == "admin":
        return {
            "modules": {k: EDIT for k in (*MODULES, *ADMIN_MODULES)},
            "actions": list(ACTIONS),
        }
    modules = grid.get("modules", {}).get(role, {})
    return {
        "modules": {
            **{k: modules.get(k, NONE) for k in MODULES},
            **{k: NONE for k in ADMIN_MODULES},
        },
        "actions": [a for a in grid.get("actions", {}).get(role, []) if a in ACTIONS],
    }


def refusal(grid: dict, role: str, method: str, path: str) -> str | None:
    """Why this role may not make this request, or None if it may."""
    if role == "admin":
        return None
    rule = rule_for(method, path)
    if rule is None:
        return "Only an admin can do that."
    if rule.module == SHARED:
        return None if level_needed(method) == VIEW else "Only an admin can do that."
    if rule.module in ADMIN_MODULES:
        return "Only an admin can do that."

    can = effective(grid, role)
    have = can["modules"].get(rule.module, NONE)
    need = level_needed(method)
    label = MODULES[rule.module]
    if have == NONE or (need == EDIT and have != EDIT):
        verb = "change" if need == EDIT else "see"
        return f"Your role can't {verb} {label}."
    if rule.action and rule.action not in can["actions"]:
        label = ACTIONS[rule.action]
        # Lower the first letter only: "approve & send to LGM", not "lgm".
        return f"Your role can't {label[0].lower()}{label[1:]}."
    return None


def validate_grid(grid: dict) -> dict:
    """A grid exactly the shape the screen edits, or ValueError.

    Unknown roles, modules, levels or actions are refused rather than dropped,
    so a typo in a client cannot silently remove somebody's access.
    """
    if not isinstance(grid, dict) or set(grid) != {"modules", "actions"}:
        raise ValueError("a grid has exactly 'modules' and 'actions'")
    modules, actions = grid["modules"], grid["actions"]
    if set(modules) != set(ROLES_IN_GRID) or set(actions) != set(ROLES_IN_GRID):
        raise ValueError(f"a grid covers exactly the roles {', '.join(ROLES_IN_GRID)}")
    clean: dict = {"modules": {}, "actions": {}}
    for role in ROLES_IN_GRID:
        row = modules[role]
        if set(row) != set(MODULES):
            missing = set(MODULES) - set(row)
            extra = set(row) - set(MODULES)
            raise ValueError(f"{role}: modules missing {sorted(missing)} or unknown {sorted(extra)}")
        for key, level in row.items():
            if level not in LEVELS:
                raise ValueError(f"{role}.{key}: level must be one of {', '.join(LEVELS)}")
        clean["modules"][role] = dict(row)
        acts = actions[role]
        if not isinstance(acts, list) or any(a not in ACTIONS for a in acts):
            raise ValueError(f"{role}: actions must be a list drawn from {', '.join(ACTIONS)}")
        clean["actions"][role] = sorted(set(acts))
    return clean
