# camayoc — quiet by default, verbose=true to debug
set quiet

default:
    just --list

# Run all quality checks (markdown lint; grows an eval gate with the first slice)
check:
    npx --yes markdownlint-cli2 "**/*.md" "!node_modules"

test:
    python3 -m unittest discover -s tests -v

# Assess a question against the competency suite. NO COVERAGE is an outcome:
# an ontology gap is reported as itself, never answered from the nearest term.
competency question:
    @python3 scripts/competency.py "{{question}}"

# The parsed suite, with its watermark.
competency-list:
    @python3 scripts/competency.py --list

# Per-question stored-query coverage for the competency suite (camayoc-102).
# A question with no stored query is an ontology GAP reported as itself.
query-coverage *args:
    @python3 scripts/query_coverage.py {{args}}
