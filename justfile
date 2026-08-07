# camayoc — quiet by default, verbose=true to debug
set quiet

default:
    just --list

# Run all quality checks (markdown lint; grows an eval gate with the first slice)
check:
    npx --yes markdownlint-cli2 "**/*.md" "!node_modules"

test:
    python3 -m unittest discover -s tests -v
