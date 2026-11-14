"""Order the members of Kotlin classes and files the way the project reads best.

Inside each class, interface and object body:
  1. properties and init blocks, in their original order (initialization order matters)
  2. secondary constructors
  3. single-line functions, together with no blank lines between them
  4. multi-line functions, each after a blank line
  5. nested types, then the companion object

At file level, top-level properties and type aliases move to the top (keeping their order),
followed by single-line functions; everything else keeps its order. Comments and annotations
directly above a declaration move with it. A multi-line declaration always has a blank line
before it. Function bodies are not changed.

Usage: layout_kotlin.py [--check] FILE...
With --check, nothing is written; files that would change are listed and the exit code is 1.
"""

import re
import sys

from layout_common import Language, run
from layout_common import layout as layout_file

MODIFIERS = (
    r"(?:(?:private|internal|public|protected|override|open|abstract|final|lateinit|const|suspend|"
    r"inline|operator|infix|tailrec|external|data|sealed|inner|enum|annotation|value|fun|"
    r"expect|actual|noinline|crossinline)\s+)*"
)

ANNOTATION = r"(?:@[\w.:]+(?:\([^)]*\))?\s+)*"

DECLARATION = re.compile(
    r"^\s*"
    + ANNOTATION
    + MODIFIERS
    + r"(?P<kind>class|interface|object|fun|val|var|typealias|constructor|init"
    + r"|companion\s+object)\b"
)

ATTACHED = re.compile(r"^\s*(//|/\*|\*|@)")

PLAIN_VALUE = re.compile(
    r"^\s*(?:val|var)\s+(?P<name>\w+)(?:\s*:\s*[\w.<>?, ]+)?\s*=\s*"
    r"(?:-?\d[\d_]*(?:\.\d+)?(?:[eE]-?\d+)?[fFLuU]?|0x[0-9A-Fa-f_]+L?|true|false|null"
    r"|\"(?:[^\"\\$]|\\.)*\"|'(?:[^'\\]|\\.)'"
    r"|(?:emptyList|emptyMap|emptySet|mutableListOf|mutableMapOf|mutableSetOf)(?:<[^>]*>)?\(\))\s*$"
)

LOCAL = re.compile(r"^\s*(?:val|var)\s+\w+")
CONTINUES = re.compile(r"^\s*(\.|\?\.|\?:|&&|\|\||[-+*/%]\s|->|\)|\]|\}|else\b|catch\b|finally\b)")
OPEN_ENDING = re.compile(r"(=|,|\(|\[|->|&&|\|\||[-+*/%]|\?:|\.)\s*$")


def line_depths(text):
    """Returns the brace and bracket depth at the start of each line, ignoring strings and
    comments.
    """
    in_string_stack = []
    braces = brackets = 0
    starts = [(0, 0)]
    i, n = 0, len(text)
    template = []  # brace depth at which each ${ ... } started
    in_string = None  # '"', '"""' or None
    while i < n:
        c = text[i]
        if in_string:
            if c == "\\" and in_string == '"':
                i += 2
                continue
            if text.startswith("${", i):
                template.append(braces)
                braces += 1
                in_string_stack.append(in_string)
                in_string = None
                i += 2
                continue
            if text.startswith(in_string, i):
                i += len(in_string)
                in_string = None
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
        if text.startswith('"""', i):
            in_string = '"""'
            i += 3
            continue
        if c == '"':
            in_string = '"'
            i += 1
            continue
        if c == "'":
            j = i + 1
            while j < n and text[j] != "'":
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if c == "{":
            braces += 1
        elif c == "}":
            braces -= 1
            if template and template[-1] == braces:
                template.pop()
                in_string = in_string_stack.pop()
        elif c in "([":
            brackets += 1
        elif c in ")]":
            brackets -= 1
        elif c == "\n":
            starts.append((braces, brackets))
        i += 1
    return starts


def group(kind, multiline):
    """Returns the sort group: variables, constructors, one-line functions, longer functions,
    types, companion.
    """
    if kind in ("val", "var", "init", "typealias"):
        return 0
    if kind == "constructor":
        return 1
    if kind == "fun":
        return 3 if multiline else 2
    if kind.startswith("companion"):
        return 5
    return 4


def is_type(kind):
    """Returns True for classes, interfaces and objects, whose bodies are laid out too."""
    return kind in ("class", "interface", "object") or kind.startswith("companion")


def skip_type(code, depths):
    """Returns True for enum bodies, which are left unchanged."""
    return bool(re.search(r"\benum\s+class\b", code[0]))


KOTLIN = Language(
    line_depths=line_depths,
    declaration=DECLARATION,
    attached=ATTACHED,
    is_type=is_type,
    group=group,
    skip_type=skip_type,
    function_kinds=("fun",),
    plain_value=PLAIN_VALUE,
    local=LOCAL,
    continues=CONTINUES,
    open_ending=OPEN_ENDING,
)


def layout(text):
    """Lays out a Kotlin file."""
    return layout_file(KOTLIN, text)


if __name__ == "__main__":
    sys.exit(run(layout))
