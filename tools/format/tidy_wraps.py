"""Undo needless line wrapping and braces in Kotlin, Swift and JavaScript.

  - A bracketed expression split over several lines goes back on one line when it fits in 100
    columns: `if (method ==\n "PUT"\n) {` becomes `if (method == "PUT") {`. A line ending in
    `=`, `&&`, `||`, `+`, `?:` or `->` is joined to the next one the same way.
  - Kotlin and JavaScript `if` / `else` bodies of a single statement lose their braces when the
    result fits on one line: `if (done) {\n return 4\n}` becomes `if (done) return 4`. Swift needs
    its braces, so it keeps them.

Nothing is joined across a comment, a multi-line string, or a block of several statements.

Usage: tidy_wraps.py [--check] FILE...
With --check, nothing is written; files that would change are listed and the exit code is 1.
"""

import re
import sys

from layout_common import run

WIDTH = 100
OPERATOR_END = re.compile(r"(\s=|&&|\|\||\s\+|\?:|->)$")
NO_SPACE_AFTER = ("(", "[", ".")
NO_SPACE_BEFORE = (")", "]", ",", ".", "?.", "!!", ";")
NESTED = re.compile(r"^(if|when|for|while|try|do|switch|else|guard|let|var|val|const)\b")
LAMBDA_PARAM = re.compile(r"^\s*([\w]+(?:\s*:\s*[\w.<>?, ]+?)?),?\s*$")
IF_HEAD = re.compile(r"^(?P<lead>\s*(?:.*?(?:=|return|->)\s+)?)if \((?P<cond>.*)\) \{$")


def strip_code(line, lang):
    """Returns (code, has_comment, has_triple_quote) for a line: string contents blanked and any
    trailing comment removed, so brackets inside strings are ignored.
    """
    out, i, n = [], 0, len(line)
    triple = '"""' in line or (lang == "js" and line.count("`") % 2 == 1)
    while i < n:
        c = line[i]
        if line.startswith("//", i) or (lang != "js" and line.startswith("/*", i)):
            return "".join(out), True, triple
        if line.startswith("/*", i):
            end = line.find("*/", i + 2)
            if end < 0:
                return "".join(out), True, triple
            i = end + 2
            continue
        if c in "\"'`" and not (lang != "js" and c == "`"):
            j = skip_string(line, i, c, lang)
            out.append(c + " " * max(0, j - i - 2) + c)
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out), False, triple


def skip_string(line, i, quote, lang):
    """Returns the index after the string literal starting at line[i]."""
    j, n = i + 1, len(line)
    while j < n:
        c = line[j]
        if c == "\\":
            if lang == "swift" and line.startswith("\\(", j):
                j = skip_group(line, j + 1, "(", ")", lang)
                continue
            j += 2
            continue
        if lang == "kotlin" and line.startswith("${", j):
            j = skip_group(line, j + 1, "{", "}", lang)
            continue
        if lang == "js" and quote == "`" and line.startswith("${", j):
            j = skip_group(line, j + 1, "{", "}", lang)
            continue
        if c == quote:
            return j + 1
        j += 1
    return n


def skip_group(line, i, open_c, close_c, lang):
    """Returns the index after the bracket group opening at line[i], skipping strings."""
    depth, j, n = 0, i, len(line)
    while j < n:
        c = line[j]
        if c in "\"'":
            j = skip_string(line, j, c, lang)
            continue
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def counts(code):
    """Returns the net (parenthesis and bracket, brace) depth change of a line of code."""
    return (
        code.count("(") + code.count("[") - code.count(")") - code.count("]"),
        code.count("{") - code.count("}"),
    )


def join(parts):
    """Joins stripped lines into one, adding spaces only where needed and dropping a trailing
    comma before a closing bracket.
    """
    text = parts[0].strip()
    for part in parts[1:]:
        piece = part.strip()
        if text.endswith(",") and piece.startswith((")", "]")):
            text = text[:-1]
        if text.endswith(NO_SPACE_AFTER) or piece.startswith(NO_SPACE_BEFORE):
            text += piece
        else:
            text += " " + piece
    return text


def unwrap_once(lines, lang):
    """Joins the first wrapped group that fits in the line width. Returns the new lines, or None."""
    info = [strip_code(line, lang) for line in lines]
    for i, line in enumerate(lines):
        code, comment, triple = info[i]
        if not line.strip() or comment or triple or code.lstrip().startswith(("*", "/*")):
            continue
        parens, _ = counts(code)
        # A line that's only "->" ends a lambda's parameters; its body stays below.
        operator = OPERATOR_END.search(code.rstrip()) and code.strip() != "->"
        if parens <= 0 and not operator:
            continue
        j, total = i, parens
        if parens > 0:
            while total > 0 and j + 1 < len(lines):
                j += 1
                total += counts(info[j][0])[0]
            if total != 0:
                continue
        else:
            # Only a complete next line: one that opens nothing and doesn't carry on itself.
            j = i + 1
            if j >= len(lines) or counts(info[j][0]) != (0, 0):
                continue
            if OPERATOR_END.search(info[j][0].rstrip()) or info[j][0].rstrip().endswith("("):
                continue
            if j + 1 < len(lines) and lines[j + 1].strip():
                first = len(line) - len(line.lstrip())
                following = lines[j + 1]
                if len(following) - len(following.lstrip()) > first:
                    continue  # the statement carries on below
                if following.strip().startswith(("?:", ".", "?.", "&&", "||", "+")):
                    continue
        group = range(i, j + 1)
        if any(info[k][1] for k in group if k != j) or any(info[k][2] for k in group):
            continue
        if any(not lines[k].strip() for k in group):
            continue
        if not braces_ok([info[k][0] for k in group]):
            continue
        if parens <= 0 and (NESTED.match(lines[j].strip()) or lines[j].strip().startswith("{")):
            continue
        indent = re.match(r"\s*", line).group(0)
        joined = indent + join([lines[k] for k in group])
        if len(joined) <= WIDTH:
            return lines[:i] + [joined] + lines[j + 1 :]
    return None


def unwrap_lambda_params(lines):
    """Joins lambda parameters split one per line back onto the line with the brace, when it
    fits.
    """
    for i, line in enumerate(lines):
        if not line.rstrip().endswith("{") or "//" in line:
            continue
        params, k = [], i + 1
        while k < len(lines) and LAMBDA_PARAM.match(lines[k]):
            params.append(LAMBDA_PARAM.match(lines[k]).group(1).strip())
            k += 1
        if params and k < len(lines) and lines[k].strip() == "->":
            joined = line.rstrip() + " " + ", ".join(params) + " ->"
            if len(joined) <= WIDTH:
                return lines[:i] + [joined] + lines[k + 1 :]
    return None


def braces_ok(codes):
    """Returns True if braces balance on every line, apart from a leading } on the first line and
    a trailing { on the last.
    """
    last = len(codes) - 1
    for k, code in enumerate(codes):
        text = code.strip()
        if k == 0 and text.startswith("}"):
            text = text[1:]
        if k == last and text.endswith("{"):
            text = text[:-1]
        if counts(text)[1] != 0:
            return False
    return True


def single_statement(line, lang):
    """Returns True if the line is one complete statement that can follow an if on the same line."""
    code, comment, triple = strip_code(line, lang)
    text = code.strip()
    return (
        text
        and not comment
        and not triple
        and counts(code) == (0, 0)
        and not NESTED.match(text)
        and not text.endswith(("{", ",", "(", "=", "&&", "||", "+", "?:", "->", "."))
        and not text.startswith(("}", ".", "?", ":", "@", "*", "//"))
    )


def drop_braces_once(lines, lang):
    """Removes the braces from the first single-statement if or if/else that fits. Returns the
    new lines, or None.
    """
    for i, line in enumerate(lines):
        m = IF_HEAD.match(line)
        if not m or i + 2 >= len(lines):
            continue
        code, comment, _ = strip_code(line, lang)
        if comment or counts(code) != (0, 1) or line.strip().startswith("}"):
            continue
        if counts(strip_code("(" + m.group("cond") + ")", lang)[0])[0] != 0:
            continue
        indent = re.match(r"\s*", line).group(0)
        body = lines[i + 1]
        if not single_statement(body, lang):
            continue
        after = lines[i + 3].strip() if i + 3 < len(lines) else ""
        head = line[: -len(" {")]
        if lines[i + 2] == indent + "}" and not after.startswith(("else", "catch")):
            joined = head + " " + body.strip()
            if len(joined) <= WIDTH:
                return lines[:i] + [joined] + lines[i + 3 :]
        if lines[i + 2] == indent + "} else {" and i + 4 < len(lines):
            other = lines[i + 3]
            if lines[i + 4] != indent + "}" or not single_statement(other, lang):
                continue
            nxt = lines[i + 5].strip() if i + 5 < len(lines) else ""
            if nxt.startswith(("else", "catch")):
                continue
            if lang == "js":
                first = head + " " + body.strip()
                second = indent + "else " + other.strip()
                if len(first) <= WIDTH and len(second) <= WIDTH:
                    return lines[:i] + [first, second] + lines[i + 5 :]
                continue
            joined = head + " " + body.strip() + " else " + other.strip()
            if len(joined) <= WIDTH:
                return lines[:i] + [joined] + lines[i + 5 :]
    return None


def tidy(text, lang):
    """Applies every rule until nothing changes. JavaScript only has braces removed, since
    Prettier already joins lines.
    """
    lines = text.split("\n")
    while True:
        new = unwrap_once(lines, lang) if lang != "js" else None
        if new is None and lang == "kotlin":
            new = unwrap_lambda_params(lines)
        if new is None and lang != "swift":
            new = drop_braces_once(lines, lang)
        if new is None:
            return "\n".join(lines)
        lines = new


def language(name):
    """Returns "kotlin", "swift" or "js" for a file name."""
    if name.endswith((".kt", ".kts")):
        return "kotlin"
    if name.endswith(".swift"):
        return "swift"
    return "js"


if __name__ == "__main__":
    names = iter(a for a in sys.argv[1:] if a != "--check")
    sys.exit(run(lambda text: tidy(text, language(next(names)))))
