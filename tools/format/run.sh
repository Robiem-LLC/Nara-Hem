#!/usr/bin/env bash
# Formats or checks every language in the repository.
#
#   tools/format/run.sh fix   [language...]   rewrite files in place
#   tools/format/run.sh check [language...]   report problems, change nothing
#
# Languages: layout python web shell kotlin swift (default: all of them).
#
# One-time setup from the repository root:
#   python3 -m venv .venv && .venv/bin/pip install -r tools/format/requirements.txt
#   npm ci
# Kotlin needs the Android SDK.
# Swift needs Xcode 16 or later (swift-format ships with it).
set -euo pipefail

mode=${1:-}
shift || true
if [[ "$mode" != fix && "$mode" != check ]]; then
  sed -n '2,13p' "$0"
  exit 2
fi
languages=("$@")
if [[ ${#languages[@]} -eq 0 ]]; then
  languages=(layout python web shell kotlin swift)
fi

root=$(git rev-parse --show-toplevel)
cd "$root"
if [[ -x .venv/bin/ruff ]]; then
  PATH="$root/.venv/bin:$PATH"
fi

failed=()

run_python() {
  if [[ $mode == fix ]]; then
    ruff format .
    ruff check --fix .
  else
    ruff format --check .
    ruff check .
  fi
}

run_web() {
  if [[ $mode == fix ]]; then
    npx prettier --write --log-level warn .
    npx eslint --fix .
  else
    npx prettier --check --log-level warn .
    npx eslint .
  fi
}

run_shell() {
  local scripts
  mapfile -t scripts < <(git ls-files '*.sh')
  if [[ $mode == fix ]]; then
    shfmt --write "${scripts[@]}"
  else
    shfmt --diff "${scripts[@]}"
  fi
  shellcheck "${scripts[@]}"
}

run_kotlin() {
  local task=ktlintCheck
  [[ $mode == fix ]] && task=ktlintFormat
  (cd apps/android && bash gradlew --quiet ":app:$task")
}

# The order of declarations: variables, then single-line functions together, then multi-line
# functions each after a blank line (see the layout_*.py tools), and no needless line wraps or
# braces (tidy_wraps.py). Runs before the formatters.
run_layout() {
  local flag=()
  [[ $mode == check ]] && flag=(--check)
  local kotlin javascript
  mapfile -t kotlin < <(git ls-files 'apps/android/*.kt')
  mapfile -t javascript < <(git ls-files '*.js' '*.mjs' '*.cjs')
  local python swift
  mapfile -t python < <(git ls-files '*.py')
  mapfile -t swift < <(git ls-files '*.swift')
  local status=0
  python3 tools/format/layout_kotlin.py "${flag[@]}" "${kotlin[@]}" || status=1
  node tools/format/layout_js.cjs "${flag[@]}" "${javascript[@]}" || status=1
  python3 tools/format/layout_python.py "${flag[@]}" "${python[@]}" || status=1
  python3 tools/format/layout_swift.py "${flag[@]}" "${swift[@]}" || status=1
  # Needless line wraps and single-statement braces (see tidy_wraps.py).
  python3 tools/format/tidy_wraps.py "${flag[@]}" "${kotlin[@]}" "${swift[@]}" "${javascript[@]}" ||
    status=1
  return $status
}

run_swift() {
  local formatter
  if command -v swift-format > /dev/null; then
    formatter=(swift-format)
  elif command -v xcrun > /dev/null; then
    formatter=(xcrun swift-format)
  else
    echo "swift: skipped (needs Xcode 16 or later)"
    return 0
  fi
  local config=apps/ios/.swift-format
  if [[ $mode == fix ]]; then
    "${formatter[@]}" format --configuration "$config" --in-place --recursive apps/ios
  else
    "${formatter[@]}" lint --configuration "$config" --strict --recursive apps/ios
  fi
}

for language in "${languages[@]}"; do
  echo "== $language"
  if ! "run_$language"; then
    failed+=("$language")
  fi
done

if [[ ${#failed[@]} -gt 0 ]]; then
  echo "Problems found in: ${failed[*]}" >&2
  exit 1
fi
echo "All clean."
