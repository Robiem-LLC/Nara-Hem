"""Move Python module and class variables above the functions and classes in the same block.

Black already puts blank lines around every function, so the remaining part of the project's
layout is that variables come first. Variables keep their order, and only move past function
and class definitions: never past other statements (calls, ifs, loops), never past a comment
that is followed by a blank line (a section heading), and never above a function or class
their value uses. Comments directly above a variable move with it.

Usage: layout_python.py [--check] FILE...
With --check, nothing is written; files that would change are listed and the exit code is 1.
"""

import ast
import sys

from layout_common import run


def names_used(node):
    """Returns every name used inside a node."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def first_line(node, lines):
    """Returns a node's first line index, including decorators and comments directly above it."""
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]) - 1
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    return start


def is_definition(node):
    """Returns True for functions and classes."""
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))


def is_variable(node):
    """Returns True for assignments and annotated assignments."""
    return isinstance(node, (ast.Assign, ast.AnnAssign))


def section_heading_between(lines, start, end):
    """Returns True if lines[start:end] contain a comment followed by a blank line."""
    for i in range(start, end - 1):
        if lines[i].lstrip().startswith("#") and not lines[i + 1].strip():
            return True
    return False


def reorder(body, lines, edits):
    """Collects (start, end, new_lines) edits for one block, then recurses into classes."""
    run = []
    previous_end = None

    def flush():
        """Reorders the current run of statements if needed and starts a new run."""
        new = []
        previous = None
        if len(run) < 2:
            run.clear()
            return
        defined = {n.name for n in run if is_definition(n)}
        variables, others = [], []
        for node in run:
            if is_variable(node) and not (names_used(node) & defined):
                variables.append(node)
            else:
                others.append(node)
        order = variables + others
        if order == run:
            run.clear()
            return
        start = first_line(run[0], lines)
        end = run[-1].end_lineno
        for node in order:
            chunk = lines[first_line(node, lines) : node.end_lineno]
            compact = (
                previous is not None
                and is_variable(node)
                and is_variable(previous)
                and len(chunk) == 1
                and previous.end_lineno == previous.lineno
            )
            if new and not compact:
                new.append("")
            new.extend(chunk)
            previous = node
        edits.append((start, end, new))
        run.clear()

    for node in body:
        movable = is_definition(node) or is_variable(node)
        heading = previous_end is not None and section_heading_between(
            lines, previous_end, first_line(node, lines)
        )
        if not movable or heading:
            flush()
        if movable:
            run.append(node)
        previous_end = node.end_lineno
        if isinstance(node, ast.ClassDef):
            reorder(node.body, lines, edits)
    flush()


def plain_value(value):
    """Returns True for a literal value that can't depend on earlier code."""
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, (ast.List, ast.Set, ast.Tuple)):
        return not value.elts
    if isinstance(value, ast.Dict):
        return not value.keys
    return isinstance(value, ast.UnaryOp) and isinstance(value.operand, ast.Constant)


def find_hoist(tree, source):
    """Returns a one-line local variable with a literal value that can move to the top of its
    function, or None. Its name must not appear in the code it would move past.
    """
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = function.body
        top = 0
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            top = 1  # the docstring
        while top < len(body) and isinstance(body[top], (ast.Assign, ast.AnnAssign)):
            top += 1
        for i in range(top + 1, len(body)):
            node = body[i]
            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and plain_value(node.value)
                and node.lineno == node.end_lineno
            ):
                continue
            name = node.targets[0].id
            source_lines = source.split("\n")
            if source_lines[node.lineno - 2].lstrip().startswith("#"):
                continue  # a comment above usually introduces the code that follows
            if isinstance(body[i - 1], (ast.Assign, ast.AnnAssign)):
                continue  # keep it with the variables it is grouped with
            passed = body[top:i]
            if any(isinstance(n, ast.Name) and n.id == name for s in passed for n in ast.walk(s)):
                continue
            if any(isinstance(n, (ast.Global, ast.Nonlocal)) for s in passed for n in ast.walk(s)):
                continue
            return node, body[top - 1] if top > 0 else None, function
    return None


def hoist_locals(text):
    """Moves eligible local variables to the top of their functions, one at a time."""
    while True:
        found = find_hoist(ast.parse(text), text)
        if not found:
            return text
        node, after, function = found
        lines = text.split("\n")
        start = node.lineno - 1
        while start > 0 and lines[start - 1].lstrip().startswith("#"):
            start -= 1
        moved = lines[start : node.end_lineno]
        del lines[start : node.end_lineno]
        target = after.end_lineno if after else function.body[0].lineno - 1
        lines[target:target] = moved
        text = "\n".join(lines)


def layout(text):
    """Lays out a Python file."""
    text = hoist_locals(text)
    # One change at a time, re-reading the code after each, so nested changes never overlap.
    while True:
        lines = text.split("\n")
        edits = []
        reorder(ast.parse(text).body, lines, edits)
        if not edits:
            return text
        start, end, new = edits[-1]
        lines[start:end] = new
        text = "\n".join(lines)


if __name__ == "__main__":
    sys.exit(run(layout))
