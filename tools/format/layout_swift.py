"""Order the members of Swift types and files the way the project reads best.

Inside each struct, class, enum, actor, protocol and extension body:
  1. properties and enum cases, in their original order (a struct's memberwise initializer
     follows its stored properties)
  2. initializers
  3. single-line functions, together with no blank lines between them
  4. multi-line functions, each after a blank line
  5. nested types and extensions

At file level, top-level constants move to the top (keeping their order), followed by
single-line functions; everything else keeps its order. Comments and attributes directly above
a declaration move with it. A body containing #if is left exactly as it is.

Inside functions, a local `let`/`var` whose value is a plain literal moves up to join the
declarations at the top of the function, unless its name appears in the code it would move past,
a comment introduces it, or it sits directly under another declaration.

Usage: layout_swift.py [--check] FILE...
With --check, nothing is written; files that would change are listed and the exit code is 1.
"""

import re
import sys

from layout_common import Language, run
from layout_common import layout as layout_file

ATTRIBUTES = r"(?:@[\w.]+(?:\([^)]*\))?\s+)*"

MODIFIERS = (
    r"(?:(?:private|fileprivate|internal|public|open|static|class|final|override|mutating|"
    r"nonmutating|lazy|weak|unowned|nonisolated|convenience|required|dynamic|indirect|"
    r"(?:private|fileprivate|internal|public)\(set\))\s+)*"
)

DECLARATION = re.compile(
    r"^\s*"
    + ATTRIBUTES
    + MODIFIERS
    + r"(?P<kind>struct|class|enum|protocol|extension|actor|typealias|func|init|deinit"
    + r"|subscript|var|let|case)\b"
)

ATTACHED = re.compile(r"^\s*(//|/\*|\*|@)")
TYPES = ("struct", "class", "enum", "protocol", "extension", "actor")
CONDITIONAL = re.compile(r"^\s*#(if|else|elseif|endif)\b")

PLAIN_VALUE = re.compile(
    r"^\s*(?:let|var)\s+(?P<name>\w+)(?:\s*:\s*[\w.<>?\[\]:, ]+)?\s*=\s*"
    r"(?:-?\d[\d_]*(?:\.\d+)?(?:[eE]-?\d+)?|0x[0-9A-Fa-f_]+|true|false|nil"
    r'|"(?:[^"\\]|\\[^(])*"|\[\]|\[:\])\s*$'
)

LOCAL = re.compile(r"^\s*(?:let|var)\s+\w+")
CONTINUES = re.compile(r"^\s*(\.|\?\?|&&|\|\||[-+*/%]\s|->|\)|\]|\}|else\b|catch\b|:)")
OPEN_ENDING = re.compile(r"(=|,|\(|\[|->|&&|\|\||[-+*/%]|\?\?|\.)\s*$")


def line_depths(text):
    """Returns the brace and bracket depth at the start of each line, ignoring strings and
    comments.
    """
    braces = brackets = 0
    starts = [(0, 0)]
    strings = []  # open string delimiters, innermost last
    interpolation = []  # bracket depth at which each \( ... ) started
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if strings and not (interpolation and interpolation[-1][1] == len(strings)):
            delimiter = strings[-1]
            if c == "\\" and text.startswith("\\(", i):
                interpolation.append((brackets, len(strings)))
                brackets += 1
                i += 2
                continue
            if c == "\\":
                if text.startswith("\n", i + 1):
                    starts.append((braces, brackets))  # a line continuation
                i += 2
                continue
            if text.startswith(delimiter, i):
                strings.pop()
                i += len(delimiter)
                continue
            if c == "\n":
                starts.append((braces, brackets))
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i)
            end = n if j < 0 else j + 2
            starts.extend([(braces, brackets)] * text.count("\n", i, end))
            i = end
            continue
        if text.startswith('#"""', i):
            strings.append('"""#')
            i += 4
            continue
        if text.startswith('#"', i):
            strings.append('"#')
            i += 2
            continue
        if text.startswith('"""', i):
            strings.append('"""')
            i += 3
            continue
        if c == '"':
            strings.append('"')
            i += 1
            continue
        if c == "{":
            braces += 1
        elif c == "}":
            braces -= 1
        elif c in "([":
            brackets += 1
        elif c in ")]":
            brackets -= 1
            if interpolation and interpolation[-1][0] == brackets:
                interpolation.pop()
        elif c == "\n":
            starts.append((braces, brackets))
        i += 1
    return starts


def group(kind, multiline):
    """Returns the sort group: properties and cases, initializers, one-line functions, longer
    functions, types.
    """
    if kind in ("var", "let", "case", "typealias"):
        return 0
    if kind in ("init", "deinit"):
        return 1
    if kind in ("func", "subscript"):
        return 3 if multiline else 2
    return 4


def is_type(kind):
    """Returns True for structs, classes, enums, actors, protocols and extensions, whose bodies
    are laid out too.
    """
    return kind in TYPES


def has_conditional(lines, depths, start, end, depth):
    """Returns True if lines[start:end] contain #if at the given depth."""
    return any(CONDITIONAL.match(lines[i]) and depths[i][0] == depth for i in range(start, end))


def skip_type(code, depths):
    """Returns True for type bodies containing #if, which are left unchanged."""
    return has_conditional(code, depths, 1, len(code), 1)


SWIFT = Language(
    line_depths=line_depths,
    declaration=DECLARATION,
    attached=ATTACHED,
    is_type=is_type,
    group=group,
    skip_type=skip_type,
    function_kinds=("func", "init"),
    plain_value=PLAIN_VALUE,
    local=LOCAL,
    continues=CONTINUES,
    open_ending=OPEN_ENDING,
    skip_file=lambda lines, depths, start, end: has_conditional(lines, depths, start, end, 0),
    skip_function=lambda body: any(CONDITIONAL.match(line) for line in body),
)


def layout(text):
    """Lays out a Swift file."""
    return layout_file(SWIFT, text)


if __name__ == "__main__":
    sys.exit(run(layout))
