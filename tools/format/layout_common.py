"""What the brace-language layout tools (Kotlin and Swift) share, plus the command line every
layout tool uses. Each language tool supplies its own patterns through a `Language`; see
layout_kotlin.py and layout_swift.py for the rules themselves.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from re import Pattern
from typing import Callable, Optional

COMMENT = re.compile(r"\s*(//|/\*|\*)")


@dataclass
class Language:
    """Language-specific patterns and callbacks used by the shared layout engine."""

    line_depths: Callable  # text -> [(brace depth, bracket depth)] at the start of each line
    declaration: Pattern  # a member's first code line; its "kind" group names what it is
    attached: Pattern  # comment and annotation lines that belong to the declaration below
    is_type: Callable  # kind -> True for classes, objects, structs and the like
    group: Callable  # (kind, multiline) -> sort group: 0 variables ... 5 last
    skip_type: Callable  # (code lines, depths) -> True to leave a type body exactly as it is
    function_kinds: tuple  # declaration kinds whose bodies get local variables hoisted
    plain_value: Pattern  # a local variable declaration with a literal value; group "name"
    local: Pattern  # any local variable declaration
    continues: Pattern  # a line that carries on the statement above it
    open_ending: Pattern  # a line that isn't finished yet
    skip_file: Optional[Callable] = None  # (lines, depths, start, end) -> leave the file alone
    skip_function: Optional[Callable] = None  # body lines -> leave that function alone


class Member:
    """A declaration together with the comments and annotations directly above it."""

    def __init__(self, lines, kind, decl_index, group):
        """lines includes the attached comments and annotations; decl_index is where the
        declaration starts.
        """
        self.lines = lines
        self.kind = kind
        self.decl_index = decl_index  # where the declaration itself starts within lines
        self._group = group

    @property
    def code(self):
        """Returns the declaration lines without attached comments."""
        return self.lines[self.decl_index :]

    @property
    def multiline(self):
        """Returns True if the declaration spans more than one line."""
        return len(self.code) > 1

    @property
    def documented(self):
        """Returns True if a comment or annotation is attached."""
        return self.decl_index > 0

    def group(self):
        """Returns the member's sort group."""
        return self._group(self.kind, self.multiline)


def split_members(lang, lines, depths, start, end, depth):
    """Splits lines[start:end] into the declarations at the given depth. Returns the lines before
    the first declaration and the members.
    """
    heads = []
    for i in range(start, end):
        if depths[i] != (depth, 0):
            continue
        m = lang.declaration.match(lines[i])
        if not m:
            continue
        j = i
        while (
            j > start
            and lang.attached.match(lines[j - 1])
            and not lang.declaration.match(lines[j - 1])
            and depths[j - 1][0] == depth
        ):
            j -= 1
        heads.append((j, i, re.sub(r"\s+", " ", m.group("kind"))))
    if not heads:
        return None, []
    prefix = lines[start : heads[0][0]]
    members = []
    for k, (first, decl, kind) in enumerate(heads):
        last = heads[k + 1][0] if k + 1 < len(heads) else end
        chunk = lines[first:last]
        while chunk and not chunk[-1].strip():
            chunk.pop()
        members.append(Member(chunk, kind, decl - first, lang.group))
    return prefix, members


def render(members, file_level):
    """Returns the members in layout order with the required blank lines."""
    out = []
    previous = None
    if file_level:
        first = [m for m in members if m.group() == 0]
        single = [m for m in members if m.group() == 2]
        rest = [m for m in members if m not in first and m not in single]
        ordered = first + single + rest
    else:
        ordered = sorted(members, key=lambda m: m.group())  # stable: keeps order within groups
    for m in ordered:
        if previous is not None:
            compact = (
                not m.multiline
                and not previous.multiline
                and not m.documented
                and m.group() == previous.group()
                and m.group() in (0, 2)
            )
            if not compact:
                out.append("")
        out.extend(m.lines)
        previous = m
    return out


def rewrite_type(lang, code):
    """Lays out the body of one type declaration."""
    depths = lang.line_depths("\n".join(code))
    if lang.skip_type(code, depths):
        return code
    inside = [i for i in range(len(code)) if depths[i][0] >= 1]
    if not inside:
        return code
    open_line = inside[0] - 1
    closing = [i for i in inside if depths[i][0] == 1 and code[i].strip().startswith("}")]
    if open_line < 0 or not closing:
        return code
    close = max(closing)
    prefix, members = split_members(lang, code, depths, open_line + 1, close, 1)
    if not members:
        return code
    for m in members:
        if lang.is_type(m.kind):
            m.lines = m.lines[: m.decl_index] + rewrite_type(lang, m.code)
    body = render(members, file_level=False)
    while prefix and not prefix[-1].strip():
        prefix.pop()
    while prefix and not prefix[0].strip():
        prefix.pop(0)
    return code[: open_line + 1] + prefix + ([""] if prefix else []) + body + code[close:]


def single_statement(lang, lines, depths, k, depth):
    """Returns True if lines[k] is a complete statement at the given body depth."""
    if depths[k] != (depth, 0) or lang.open_ending.search(lines[k]):
        return False
    following = k + 1 < len(lines) and lines[k + 1].strip() and depths[k + 1] == (depth, 0)
    return not (following and lang.continues.match(lines[k + 1]))


def function_body(lang, lines, depths, i):
    """Returns the body line indexes and depth of the function declared on line i, or None."""
    depth = depths[i][0] + 1
    open_line = i
    body = []
    while open_line + 1 < len(lines) and depths[open_line + 1][0] < depth:
        if depths[open_line + 1][0] < depths[i][0] or open_line - i > 20:
            break
        open_line += 1
    if open_line + 1 >= len(lines) or depths[open_line + 1][0] != depth:
        return None
    if not lines[open_line].rstrip().endswith("{"):
        return None
    k = open_line + 1
    while k < len(lines) and depths[k][0] >= depth:
        if depths[k][0] == depth and lines[k].strip().startswith("}"):
            if k + 1 >= len(lines) or depths[k + 1][0] < depth:
                break
        body.append(k)
        k += 1
    return body, depth


def find_hoist(lang, lines, depths):
    """Returns a local variable with a literal value that can move to the top of its function, or
    None. It stays if its name appears in the code it would move past, if a comment introduces
    it, or if it directly follows another declaration.
    """
    for i, line in enumerate(lines):
        m = lang.declaration.match(line)
        if not m or m.group("kind") not in lang.function_kinds:
            continue
        found = function_body(lang, lines, depths, i)
        if not found:
            continue
        body, depth = found
        if lang.skip_function and lang.skip_function([lines[b] for b in body]):
            continue
        statements = [
            b
            for b in body
            if depths[b] == (depth, 0) and lines[b].strip() and not COMMENT.match(lines[b])
        ]
        top = 0
        while (
            top < len(statements)
            and lang.local.match(lines[statements[top]])
            and single_statement(lang, lines, depths, statements[top], depth)
        ):
            top += 1
        for s in statements[top + 1 :]:
            m = lang.plain_value.match(lines[s])
            if not m or not single_statement(lang, lines, depths, s, depth):
                continue
            if s > 0 and depths[s - 1] != (depth, 0) and lines[s - 1].strip():
                continue  # follows an unfinished statement
            if lines[s - 1].strip().startswith(("//", "/*", "*")):
                continue
            if lang.local.match(lines[s - 1]):
                continue
            target = statements[top] if top < len(statements) else s
            between = "\n".join(lines[target:s])
            if re.search(r"(?<![\w.])" + m.group("name") + r"\b", between):
                continue
            return s, target
    return None


def hoist_locals(lang, text):
    """Moves eligible local variables to the top of their functions, one at a time."""
    while True:
        lines = text.split("\n")
        found = find_hoist(lang, lines, lang.line_depths(text))
        if not found:
            return text
        s, target = found
        moved = lines[s : s + 1]
        del lines[s : s + 1]
        # Go above any comment lines that belong to the statement at the target.
        while target > 0 and lines[target - 1].lstrip().startswith("//"):
            target -= 1
        lines[target:target] = moved
        new = "\n".join(lines)
        if new == text:
            return text  # nothing moved; never loop
        text = new


def layout(lang, text):
    """Lays out a whole file: hoisted locals, ordered members and blank lines."""
    text = hoist_locals(lang, text)
    lines = text.split("\n")
    depths = lang.line_depths(text)
    assert len(depths) == len(lines), "line count mismatch"
    first_decl = next(
        (i for i, line in enumerate(lines) if depths[i] == (0, 0) and lang.declaration.match(line)),
        None,
    )
    if first_decl is None:
        return text
    head_end = first_decl
    while (
        head_end > 0
        and lang.attached.match(lines[head_end - 1])
        and not lang.declaration.match(lines[head_end - 1])
    ):
        head_end -= 1
    tail_end = len(lines)
    while tail_end > 0 and not lines[tail_end - 1].strip():
        tail_end -= 1
    if lang.skip_file and lang.skip_file(lines, depths, head_end, tail_end):
        return text
    prefix, members = split_members(lang, lines, depths, head_end, tail_end, 0)
    for m in members:
        if lang.is_type(m.kind):
            m.lines = m.lines[: m.decl_index] + rewrite_type(lang, m.code)
    header = lines[:head_end]
    while header and not header[-1].strip():
        header.pop()
    return "\n".join(header + [""] + render(members, file_level=True)) + "\n"


def run(layout_text):
    """Command line for the layout tools: tool [--check] FILE... Rewrites files, or with --check
    lists files that would change and exits with 1.
    """
    args = sys.argv[1:]
    check = "--check" in args
    changed = []
    for name in (a for a in args if a != "--check"):
        path = Path(name)
        old = path.read_text()
        new = layout_text(old)
        if new != old:
            changed.append(name)
            if not check:
                path.write_text(new)
    for name in changed:
        print(("needs layout: " if check else "laid out: ") + name)
    return 1 if check and changed else 0
