<p align="center">
  <img src="assets/logo.svg" width="200" alt="Camayoc logo — loose gray strands enter from the left, the keeper's yupana counting board hangs from the main cord at center, and ordered, colored, knotted quipu pendants emerge on the right"/>
</p>

<h1 align="center">camayoc</h1>

<p align="center">
  <em>🧶 Agents that check what was already decided, and record new decisions with how they know</em>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License: Apache-2.0"/></a>
  <a href="https://github.com/scbrown/camayoc/actions/workflows/ci.yml"><img src="https://github.com/scbrown/camayoc/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://github.com/scbrown/caboodle"><img src="https://img.shields.io/badge/stack-quipu-8B5E3C.svg" alt="Part of the caboodle stack"/></a>
</p>

**Camayoc gives AI coding agents a governed memory: a starter vocabulary for
work, decisions and outcomes, loaded into a [quipu](https://github.com/scbrown/quipu)
knowledge graph that refuses any record that does not say how it was learned
(observed, declared or inferred).** It is for teams whose agents keep
re-deciding things a past session already settled. It comes as a Claude Code
plugin (a skill, a session-start status hook and a bootstrap command), and as
plain scripts any agent that speaks HTTP can use.

The *quipucamayoc* was the Inca official who kept the quipus and certified what
was read back out of them.

## Why you would want it

- **Agents ask before they re-decide.** The skill has them query what was
  already decided, and why, before choosing again.
- **Every fact says how it was learned.** A record without an honest
  `observed` / `declared` / `inferred` tag is refused at write, so a guess
  cannot pass as an observation.
- **It proves its own gate.** Bootstrap sends records that must be refused and
  fails loudly if the store accepts one.

The long form (its place in the stack, what runs today, what it deliberately is
not): [Why camayoc](https://scbrown.github.io/camayoc/why-camayoc.html).

## Install

As a Claude Code plugin, in Claude Code:

```text
/plugin marketplace add scbrown/camayoc
/plugin install camayoc@camayoc
```

From a shell, for any other agent or for scripts:

```bash
git clone --depth 1 https://github.com/scbrown/camayoc
```

There is nothing else to install first: bootstrap brings its own quipu.

## First success in three commands

From an empty directory, bootstrap a governed memory and watch it prove its gate:

```bash
git clone -q --depth 1 https://github.com/scbrown/camayoc
QUIPU_SERVER=http://127.0.0.1:3030 bash camayoc/scripts/bootstrap.sh > bootstrap.log 2>&1
grep -E '^(ontology|shapes|gate: PROVEN — an untagged|camayoc:)' bootstrap.log
```

```text
ontology: loaded (core.ttl)
shapes: loaded (camayoc-core)
gate: PROVEN — an untagged Decision refused, as it must be.
camayoc: governed memory ready. Query first; record at the moment; tag honestly.
```

With no quipu on your machine, bootstrap downloaded one (sha256-checked),
started it, loaded the vocabulary and shapes, and then tried to write a
Decision with no provenance tag. The store refused it. That refusal is the
guarantee everything else rests on. Stop the server with
`kill "$(cat .quipu/server.pid)"`; the full log is in `bootstrap.log`.

## On your own data

| you want to | run |
|---|---|
| check whether a question is covered by the competency suite | `python3 camayoc/scripts/competency.py "<question>"` |
| map a question to a stored query with Jev (needs a TypeSafe key) | `python3 camayoc/scripts/competency.py --map "<question>"` |
| preview an advisory ordered-rubric benchmark without a key | `just jev-bench bench/ordinal/na-htm.jsonl --slot ordinal` ([pilot and replay](bench/ordinal/README.md)) |
| see which competency questions have a stored query | `python3 camayoc/scripts/query_coverage.py` |
| check a proposal against decisions already made | `python3 camayoc/scripts/settled_decisions.py "<proposal>" --declared <file>` |
| see the quarantine planes and their labels | `python3 camayoc/scripts/planes.py status` |

Every script: [Reference](https://scbrown.github.io/camayoc/reference.html).

## Wire it into your agent

With the plugin installed, run this once in Claude Code:

```text
/camayoc:bootstrap
```

It does what the shell bootstrap does, then offers the rest of the stack.
From then on every session opens with a memory status line (`ACTIVE`,
`reachable but gate not proven`, or `unreachable`), and the skill teaches the
agent to query first, record at the moment, and tag honestly. Without the
plugin, `bash camayoc/scripts/bootstrap.sh --with-claude-hooks` adds the same
status hook to `.claude/settings.json`. The plugin also declares a `jev` MCP
server for typed decisions. Details: [Using it with agents](https://scbrown.github.io/camayoc/agents.html).

## Before you start

**Platforms.** Bootstrap downloads a quipu release on Linux x86_64. On other
platforms it builds quipu with `cargo`, or uses a `quipu-server` already on
your `PATH`. The scripts need `bash`, `curl` and `python3`.

**Exit codes.** Bootstrap exits 1 if nothing could be installed, 2 if the store
accepted a record it must refuse, and 3 if no verdict could be reached. See
[Getting started](https://scbrown.github.io/camayoc/getting-started.html#when-something-fails).

## What's next

- [The camayoc book](https://scbrown.github.io/camayoc/): getting started, agents, reference and the design notes, in reading order
- [Docs map](https://scbrown.github.io/camayoc/docs-map.html): every document in this repository, routed
- [Ingress](https://scbrown.github.io/camayoc/design/ingress.html): how knowledge earns its way into the graph

## 🧺 The stack

Caboodle installs these together and proves each one works; every tool also stands alone.

| tool | what it gives your agents |
|---|---|
| [caboodle](https://github.com/scbrown/caboodle) | one wizard that installs the stack and proves it works |
| [quipu](https://github.com/scbrown/quipu) | a knowledge graph that refuses facts that break its rules |
| [camayoc](https://github.com/scbrown/camayoc) **(you are here)** | the starter vocabulary, and how new knowledge earns its way in |
| [bobbin](https://github.com/scbrown/bobbin) | search and context over your repositories, served over MCP |
| [yupana](https://github.com/scbrown/yupana) | which code calls which: the blast radius before an edit |
| [desire-path](https://github.com/scbrown/desire-path) | the tool calls your agents get wrong, so you can fix them |

## Contributing

```bash
just test
just check   # the local quality gate
```

## 📜 License

[Apache-2.0](LICENSE)
