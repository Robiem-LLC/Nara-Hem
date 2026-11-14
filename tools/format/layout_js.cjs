// Order top-level JavaScript declarations the way the project reads best:
//   1. variables (const/let), in their original order
//   2. single-line functions, together with no blank lines between them
//   3. multi-line functions, each after a blank line
// Statements that run when the file loads (calls, tests, exports of expressions) stay where they
// are, and declarations are only reordered between them. A function kept in a const stays with
// the variables when a variable's initializer mentions it, so nothing is used before it exists.
// Comments directly above a declaration move with it. Function bodies are not changed.
//
// Usage: node tools/format/layout_js.cjs [--check] FILE...
// With --check, nothing is written; files that would change are listed and the exit code is 1.
const fs = require('fs');
const espree = require('espree');

/** Sort group for variables. */
const VARIABLE = 0;

/** Sort group for one-line functions. */
const SINGLE = 1;

/** Sort group for longer functions. */
const MULTI = 2;

/** Parses JavaScript into an AST, or returns null on a syntax error. */
function parse(text) {
  const options = { ecmaVersion: 'latest', range: true, loc: true, comment: true };
  try {
    return espree.parse(text, { ...options, sourceType: 'module' });
  } catch {
    return espree.parse(text, { ...options, sourceType: 'script' });
  }
}

/** Returns the declaration inside an export, or the node itself. */
function declarationOf(node) {
  return node.type === 'ExportNamedDeclaration' && node.declaration ? node.declaration : node;
}

/** Returns true if a variable's initializer is a function. */
function isFunctionValue(init) {
  return init && (init.type === 'ArrowFunctionExpression' || init.type === 'FunctionExpression');
}

/** Returns the sort group of a top-level statement, or null if it must not move. */
function classify(node) {
  const inner = declarationOf(node);
  const lines = node.loc.end.line - node.loc.start.line + 1;
  if (inner.type === 'FunctionDeclaration') return lines === 1 ? SINGLE : MULTI;
  if (inner.type === 'VariableDeclaration') {
    const [only] = inner.declarations;
    if (inner.declarations.length === 1 && inner.kind === 'const' && isFunctionValue(only.init)) {
      return lines === 1 ? SINGLE : MULTI;
    }
    return VARIABLE;
  }
  return null; // a statement: it runs in place
}

/** Returns the name a declaration defines. */
function nameOf(node) {
  const inner = declarationOf(node);
  if (inner.type === 'FunctionDeclaration') return inner.id.name;
  if (inner.type === 'VariableDeclaration') return inner.declarations[0].id.name;
  return null;
}

/** Lays out a JavaScript file. */
function layout(text) {
  const ast = parse(text);
  const body = ast.body;
  const firstCode = body.findIndex((node) => node.type !== 'ImportDeclaration');
  // Each item: its source text including the comments and blank lines before it.
  const items = [];
  // Runs of declarations between statements are reordered; statements stay as they are.
  const output = [];
  let run = [];
  let previous = null;
  if (firstCode < 0) return text;
  let previousEnd = firstCode > 0 ? body[firstCode - 1].range[1] : null;
  if (previousEnd === null) {
    // Keep a file's leading comment block (before the first statement) as the header.
    const leading = ast.comments.filter((c) => c.range[1] <= body[0].range[0]);
    const attached = [];
    for (let i = leading.length - 1; i >= 0; i--) {
      const gap = text.slice(
        leading[i].range[1],
        i === leading.length - 1 ? body[0].range[0] : attached[0].range[0],
      );
      if ((gap.match(/\n/g) || []).length > 1) break;
      attached.unshift(leading[i]);
    }
    // The header ends after the last comment that is not attached to the first statement.
    const detached = leading.filter((c) => !attached.includes(c));
    previousEnd = detached.length ? detached[detached.length - 1].range[1] : 0;
  }
  const header = text.slice(0, previousEnd);
  for (const node of body.slice(firstCode)) {
    let chunk = text.slice(previousEnd, node.range[1]);
    // A comment followed by a blank line is a section heading: it stays where it is.
    const lead = text.slice(previousEnd, node.range[0]);
    const lastBlank = lead.search(/\n[ \t]*\n(?![\s\S]*\n[ \t]*\n)/);
    if (lastBlank >= 0 && /\/\/|\/\*/.test(lead.slice(0, lastBlank))) {
      const heading = lead.slice(0, lastBlank);
      items.push({
        node: null,
        text: heading,
        group: null,
        comment: true,
        name: null,
        lines: heading.trim().split('\n').length,
        blankBefore: (heading.match(/^\s*/)[0].match(/\n/g) || []).length > 1,
      });
      chunk = chunk.slice(lastBlank);
    }
    const comment = /^\s*(\/\/|\/\*)/.test(chunk);
    const blankBefore = (chunk.match(/^\s*/)[0].match(/\n/g) || []).length > 1;
    const lines = node.loc.end.line - node.loc.start.line + 1;
    items.push({
      node,
      text: chunk,
      group: classify(node),
      comment,
      name: nameOf(node),
      blankBefore,
      lines,
    });
    previousEnd = node.range[1];
  }
  const trailing = text.slice(previousEnd);

  const flush = () => {
    if (!run.length) return;
    // A const function stays with the variables if a variable's initializer names it.
    const variableText = run.filter((i) => i.group === VARIABLE).map((i) => i.node);
    for (const item of run) {
      if (item.group === VARIABLE || !item.name) continue;
      const inner = declarationOf(item.node);
      if (inner.type !== 'VariableDeclaration') continue;
      const pattern = new RegExp(`\\b${item.name}\\b`);
      if (variableText.some((v) => pattern.test(text.slice(...v.range)))) item.group = VARIABLE;
    }
    const ordered = [...run].sort((a, b) => a.group - b.group); // stable
    // Where the run meets the code around it, keep the spacing it had.
    ordered[0] = { ...ordered[0], edgeBlank: run[0].blankBefore };
    output.push(...ordered);
    run = [];
  };
  for (const item of items) {
    if (item.group === null) {
      flush();
      output.push(item);
    } else {
      run.push(item);
    }
  }
  flush();

  let result = header.trimEnd();
  for (const item of output) {
    const multiline = item.lines > 1;
    const multiFunction = item.group === MULTI;
    let blank;
    if (item.group === null || item.edgeBlank !== undefined) {
      // Statements, and the first declaration after them, keep their original spacing.
      blank = item.group === null ? item.blankBefore : item.edgeBlank;
      blank = blank || multiFunction || previous?.group === MULTI;
    } else {
      const compact =
        previous !== null &&
        previous.group === item.group &&
        item.group !== MULTI &&
        !multiline &&
        !previous.multiline &&
        !item.comment;
      blank = !compact;
    }
    if (result) result += blank ? '\n\n' : '\n';
    result += item.text.trim();
    previous = { ...item, multiline };
  }
  return result + (trailing.trim() ? trailing : '\n');
}

/** Returns true for a literal value that can't depend on earlier code. */
function isPlainValue(init) {
  if (!init) return true;
  if (init.type === 'Literal') return true;
  if (init.type === 'TemplateLiteral') return init.expressions.length === 0;
  if (init.type === 'ArrayExpression') return init.elements.length === 0;
  if (init.type === 'ObjectExpression') return init.properties.length === 0;
  if (init.type === 'UnaryExpression') return init.argument.type === 'Literal';
  return false;
}

/**
 * Returns a local variable with a literal value that can move to the top of its function, or null.
 * Its name must not appear in the code it would move past.
 */
function findHoist(text, ast) {
  let found = null;
  const visit = (node) => {
    if (found || !node || typeof node.type !== 'string') return;
    if (/Function/.test(node.type) && node.body?.type === 'BlockStatement') {
      const statements = node.body.body;
      let top = 0;
      while (top < statements.length && statements[top].type === 'VariableDeclaration') top++;
      for (let i = top + 1; i < statements.length && !found; i++) {
        const s = statements[i];
        if (s.type !== 'VariableDeclaration' || s.declarations.length !== 1) continue;
        const [d] = s.declarations;
        if (d.id.type !== 'Identifier' || !isPlainValue(d.init)) continue;
        const between = text.slice(statements[top].range[0], s.range[0]);
        if (new RegExp(`(^|[^\\w$.])${d.id.name}([^\\w$]|$)`).test(between)) continue;
        if (text.slice(s.range[0], s.range[1]).includes('\n')) continue;
        // A comment above usually introduces the code that follows: leave both in place.
        const lineBefore = text.slice(
          lineStart(text, lineStart(text, s.range[0]) - 1),
          lineStart(text, s.range[0]),
        );
        if (/^\s*(\/\/|\/\*|\*)/.test(lineBefore)) continue;
        // Keep it with the declarations it is grouped with.
        if (statements[i - 1].type === 'VariableDeclaration') continue;
        found = { statement: s, after: top > 0 ? statements[top - 1] : null, body: node.body };
      }
    }
    for (const key of Object.keys(node)) {
      const child = node[key];
      if (Array.isArray(child)) child.forEach(visit);
      else if (child && typeof child.type === 'string') visit(child);
    }
  };
  visit(ast);
  return found;
}

/** Returns the index of the start of the line containing index. */
function lineStart(text, index) {
  return text.lastIndexOf('\n', index - 1) + 1;
}

/** Moves eligible local variables to the top of their functions, one at a time. */
function hoistLocals(text) {
  for (;;) {
    const move = findHoist(text, parse(text));
    if (!move) return text;
    const { statement, after, body } = move;
    // The line(s) to move: the declaration and any comment lines directly above it.
    let start = lineStart(text, statement.range[0]);
    for (;;) {
      const previous = lineStart(text, start - 1);
      if (start === 0 || !/^\s*(\/\/|\/\*|\*)/.test(text.slice(previous, start))) break;
      start = previous;
    }
    const end = text.indexOf('\n', statement.range[1]) + 1;
    const moved = text.slice(start, end);
    const target = after
      ? text.indexOf('\n', after.range[1]) + 1
      : text.indexOf('\n', body.range[0]) + 1;
    text = text.slice(0, target) + moved + text.slice(target, start) + text.slice(end);
  }
}

/** Command line: layout_js.cjs [--check] FILE... */
function main() {
  const args = process.argv.slice(2);
  const check = args.includes('--check');
  const changed = [];
  for (const file of args.filter((a) => a !== '--check')) {
    const old = fs.readFileSync(file, 'utf8');
    const updated = layout(hoistLocals(old));
    if (updated !== old) {
      changed.push(file);
      if (!check) fs.writeFileSync(file, updated);
    }
  }
  for (const file of changed) console.log((check ? 'needs layout: ' : 'laid out: ') + file);
  process.exitCode = check && changed.length ? 1 : 0;
}

main();
