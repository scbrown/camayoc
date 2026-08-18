# camayoc — quiet by default, verbose=true to debug
set quiet

default:
    just --list

# Run all quality checks (markdown lint; grows an eval gate with the first slice)
check:
    npx --yes markdownlint-cli2 "**/*.md" "!node_modules"

test:
    python3 -m unittest discover -s tests -v

# Emit the work-item provenance chain from git history (docs/design/ingress.md
# §3.3). Deterministic and abstaining: a commit naming no recognised work item
# emits nothing. Pass --project for every tracker prefix in play — an
# undeclared one is silently unlinked, and the summary is where you see it.
ingest-git *args:
    @python3 scripts/ingest_git_provenance.py {{args}}

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
