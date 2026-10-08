"""Find the backtick that ends an Angular template early.

A component's markup lives in a template literal:

    @Component({ template: `<div>…</div>`, styles: [`…`] })

so a backtick *inside* that markup closes it, and everything after is parsed as
TypeScript. The compiler then reports `TS-991002: Incorrect number of arguments
to @Component decorator` and a cascade of "cannot find name" errors pointing
nowhere near the real line. It cost five builds in one session, every time from
the same thing: a comment quoting an identifier the way prose does.

    <!-- the `contact_profile` type sat here looking like a profile -->
    /* a global `.slot` turned these cards into flex rows */

This is not a lint rule, because by the time a stray backtick exists the file no
longer parses and a linter has nothing to walk. It is a scanner: it finds each
template literal, walks it the way the language does — honouring escapes and
`${}` interpolation — and asks what follows the closing backtick. A literal that
ends properly is followed by `,` `}` `]` or `)`. One that ends in the middle of
a comment is followed by prose, and that is the bug, reported at its own line.

No dependencies, so it runs where `npm install` cannot.

    python check_templates.py            # the whole app
    python check_templates.py src/app/accounts
"""

from __future__ import annotations

import sys
from pathlib import Path

#: What may legally follow a template literal that ended where it meant to:
#: another argument, the end of the decorator object, the end of a styles
#: array, the end of a call.
AFTER_CLOSE = ",}])"

#: The properties whose values are template literals. `template` and `styles`
#: are the ones that hold markup; the others are here because the same mistake
#: in any tagged literal produces the same unreadable error.
KEYS = ("template:", "styles:", "styleUrls:")


def _close_of(text: str, start: int) -> int | None:
    """Index of the backtick that closes the literal opened at `start`.

    Walks as the language does: a backslash escapes the next character, and
    `${` opens an interpolation that runs to its matching brace, inside which a
    backtick is code rather than a terminator.
    """
    i = start + 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "$" and text[i + 1 : i + 2] == "{":
            depth = 1
            i += 2
            while i < len(text) and depth:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                i += 1
            continue
        if c == "`":
            return i
        i += 1
    return None


def _next_meaningful(text: str, i: int) -> str:
    """The first character after `i` that is not whitespace or a comment.

    Comments count: `template: \\`…\\` /* why */,` is legal, and treating the
    slash as prose would report a file that compiles perfectly well.
    """
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i == -1:
                return ""
        elif text.startswith("/*", i):
            end = text.find("*/", i)
            if end == -1:
                return ""
            i = end + 2
        else:
            return text[i]
    return ""


def check(path: Path) -> list[str]:
    """Problems in one file, as printable lines. Empty means it is fine."""
    text = path.read_text(encoding="utf-8", errors="replace")
    problems: list[str] = []
    at = 0
    while True:
        found = [(p, k) for k in KEYS if (p := text.find(k, at)) != -1]
        if not found:
            return problems
        key_at, key = min(found)
        after_key = key_at + len(key)
        tick = text.find("`", after_key)
        if tick == -1:
            return problems
        # Only a backtick on the same logical span as the key. A `styles: [`
        # puts a bracket and a newline between them, which is fine; a key with
        # no literal at all (styleUrls: ['a.css']) must not reach forward and
        # swallow the next property's template.
        if any(ch not in " \t\r\n[" for ch in text[after_key:tick]):
            at = after_key
            continue

        close = _close_of(text, tick)
        if close is None:
            line = text.count("\n", 0, tick) + 1
            problems.append(
                f"{path}:{line}: template literal is never closed - "
                f"a backtick is missing, or one inside was meant to be escaped"
            )
            return problems

        following = _next_meaningful(text, close + 1)
        if following and following not in AFTER_CLOSE:
            line = text.count("\n", 0, close) + 1
            snippet = text[close + 1 : close + 48].split("\n")[0].strip()
            problems.append(
                f"{path}:{line}: a backtick here ends the template early - "
                f"followed by {snippet!r}, not the end of the property.\n"
                f"    Escape it (\\`) or write the name without backticks."
            )
            # Everything after this point is parsed wrongly too, so a second
            # report would be noise about the same mistake.
            return problems
        at = close + 1


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("src")
    if not root.exists():
        print(f"nothing to check: {root} does not exist")
        return 2

    files = sorted(root.rglob("*.ts")) if root.is_dir() else [root]
    problems: list[str] = []
    for path in files:
        if path.name.endswith(".spec.ts"):
            continue
        problems.extend(check(path))

    for problem in problems:
        print(problem)
    print(
        f"\n{len(files)} file(s) checked, {len(problems)} problem(s)."
        if problems
        else f"{len(files)} file(s) checked, every template literal closes where it should."
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
