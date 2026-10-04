"""Structural integrity check for prospect-engine-ui.html.

Run after every edit. Catches the failure mode that bit us three times:
a splice removing a panel while leaving the button that opens it, so the
tab renders blank with no error anywhere.

    python mockups/check_ui.py
"""
import io, re, sys, pathlib

HTML = pathlib.Path(__file__).with_name("prospect-engine-ui.html")
s = io.open(HTML, encoding="utf-8").read()
problems, checks = [], 0


def panels(attr):
    """Panels declared as containers, not as the buttons that open them."""
    return set(re.findall(r'<(?:section|div)[^>]*class="[^"]*(?:view|subview)[^"]*"[^>]*%s="([^"]+)"' % attr, s))


def buttons(attr):
    return set(re.findall(r'<button[^>]*%s="([^"]+)"' % attr, s))


# 1. every nav button has a view, and every view is reachable
nav, views = buttons("data-nav"), panels("data-view")
routed = set(re.findall(r"navForView\s*=\s*\{([^}]*)\}", s)[0].count and
             re.findall(r"(\w+)\s*:\s*'[^']*'", re.findall(r"navForView\s*=\s*\{([^}]*)\}", s)[0])) if "navForView" in s else set()
checks += 1
for n in sorted(nav - views):
    problems.append("nav '%s' has no <section data-view>" % n)
for v in sorted(views - nav - routed):
    problems.append("view '%s' is unreachable (no nav item, not in navForView)" % v)

# 2. every tab button has a matching panel
for attr in ("data-sub", "data-camp", "data-set", "data-dash", "data-out"):
    checks += 1
    b, pan = buttons(attr), panels(attr)
    for x in sorted(b - pan):
        problems.append("%s='%s' button has no panel" % (attr, x))
    for x in sorted(pan - b):
        problems.append("%s='%s' panel has no button" % (attr, x))

# 3. exactly one default-active panel per tab group
for attr in ("data-sub", "data-camp", "data-set", "data-dash", "data-out"):
    checks += 1
    act = re.findall(r'class="subview active"[^>]*%s="([^"]+)"' % attr, s)
    if panels(attr) and len(act) != 1:
        problems.append("%s: expected exactly 1 active panel by default, found %d" % (attr, len(act)))

# 4. no panel is suspiciously empty
checks += 1
for m in re.finditer(r'<(section|div)[^>]*class="(?:view|subview)[^"]*"[^>]*data-(?:view|sub|camp|set|dash|out)="([^"]+)"[^>]*>', s):
    body = s[m.end(): m.end() + 400]
    if len(re.sub(r"<[^>]+>|\s", "", body)) < 12:
        problems.append("panel '%s' looks empty" % m.group(2))

# 5. div balance
checks += 1
opens = len(re.findall(r"<div\b", s))
closes = len(re.findall(r"</div>", s))
if opens != closes:
    problems.append("div imbalance: %d <div> vs %d </div>" % (opens, closes))

# 6. every onclick handler is defined
checks += 1
defined = set(re.findall(r"function\s+(\w+)\s*\(", s)) | {"toast"}
for fn in sorted(set(re.findall(r'onclick="(\w+)\(', s))):
    if fn not in defined:
        problems.append("onclick calls undefined function '%s'" % fn)

# 7. every form key referenced by openForm exists in FORMS
checks += 1
form_keys = set(re.findall(r"^\s{4}(\w+):\s*\{", s, re.M))
for k in sorted(set(re.findall(r"openForm\('([^']+)'\)", s))):
    if k not in form_keys:
        problems.append("openForm('%s') has no FORMS entry" % k)

print("checked %d rule groups over %d lines" % (checks, s.count("\n") + 1))
if problems:
    print("\nFAIL — %d problem(s):" % len(problems))
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("PASS — no structural problems")
