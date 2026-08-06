# camayoc — quiet by default, verbose=true to debug
set quiet

default:
    just --list

# Run all quality checks (markdown lint; grows an eval gate with the first slice)
check:
    npx --yes markdownlint-cli2 "**/*.md" "!node_modules"

# Placeholder until the first slice lands its eval gate
test:
    echo "no tests yet — the competency suite becomes the gate (see docs/design/task-lifecycle-slice.md §4)"
