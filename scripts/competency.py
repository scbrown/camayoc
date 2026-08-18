#!/usr/bin/env python3
"""The competency suite, machine-readable, and a NO COVERAGE verdict — camayoc-b6h.

## What b6h asks for and what it actually needs first

b6h wants an incoming question whose best match against the competency suite falls
below threshold reported as **NO COVERAGE** — an ontology gap surfaced as its own
outcome, never silently answered from the nearest term. The bead names embeddings as
the matcher.

Embeddings are blocked here, measured rather than assumed, and re-measured on
2026-08-18: the weight download redirects to a CDN the network policy denies
(`us.aws.cdn.hf.co:443`, 403 on CONNECT — confirmed at the proxy itself, not
just at curl). `models/all-MiniLM-L6-v2` holds a tokenizer and a config and no
weights. That blocks *scoring*. It does not block anything else, and two things
had to exist before any matcher could run at all:

1. **The suite was not machine-readable.** It is prose in three markdown files.
   Nothing can be embedded, scored or reported against until it parses.
2. **The verdict had no shape.** "Below threshold" means nothing without a recorded
   threshold, a recorded method, and a way to tell whether the suite you scored
   against is the suite on disk.

Both are here, plus a deterministic matcher so the discipline runs today —
and, since 2026-08-18, the embedding path itself. `Scorer` selects between the
two at construction and reports which one ran; when weights land, nothing about
the discipline changes, only the label and the numbers. The label and the
`semantic` flag derive from the same decision that picks the scoring function,
so they cannot disagree — a verdict claiming `semantic: true` over a
word-overlap number is precisely the masquerade this file exists to prevent,
and holding them as independent constants is how that happens.

## The rule this file exists to obey

camayoc's ingress discipline is that model-inferred facts are tagged and never
masquerade as observed ones. The inverse binds just as hard: **a lexical score must
never be presented as a semantic one.** So every verdict carries `method`, and the
deterministic matcher names itself `lexical-jaccard-v1` — not "similarity", not
"match", not anything a reader could mistake for meaning-aware. When weights land,
the method string changes and old verdicts remain readable as what they were.

The scorer is word overlap. It will miss a question that means the same thing in
different words, and that failure mode is exactly the one embeddings fix. Reporting
NO COVERAGE when coverage exists is the safe direction — it files a spurious gap,
which a human reads and dismisses. The unsafe direction is answering from the
nearest term, and no threshold setting here can produce that.

## Empty / Partial / Full

The same discipline quipu's coverage query uses, applied to the ontology's own reach:

  Full     a question at or above the full threshold — the suite covers this.
  Partial  above the advisory floor, below full — related questions exist, but
           nothing that answers it. A candidate for a new competency question.
  Empty    below the floor — NO COVERAGE. An ontology gap, reported as itself.

Stage-1 advisory, per the bead: this identifies and informs. It refuses nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Sections that are not questions. "Acceptance" states when a slice is done.
NON_QUESTION_SECTIONS = ("acceptance",)

#: Numbered-item start. Question numbers restart per file and are not contiguous
#: (metrics-and-requirements.md runs 1-11 then 22-23), so the id is composite.
ITEM = re.compile(r"^(\d+)\.\s+(.*)$")
HEADING = re.compile(r"^##\s+(.*)$")
PARAMETER = re.compile(r"<([^<>]+)>")

#: Words carrying no discriminating power in a suite where every entry is a
#: question about a knowledge graph. Kept short and explicit rather than a
#: borrowed stopword list, because each one here is a deliberate choice.
NOISE = frozenset(
    """a an and are as at be been by did do does for from has have how i in is it its
    of on or that the their them there these this to was were what when where which
    who whom whose why will with would""".split()
)

#: The method label for the deterministic scorer. Changing the algorithm MUST
#: change this string — a verdict whose method is a lie is worse than no verdict.
LEXICAL_METHOD = "lexical-jaccard-v1"

#: The method label for the embedding scorer, used only when weights load.
EMBEDDING_METHOD = "embedding-minilm-l6-v2"

#: Where model weights would live. Overridable so a caller with weights
#: elsewhere can point at them without editing this file.
MODEL_DIR = Path(
    os.environ.get(
        "CAMAYOC_MODEL_DIR",
        Path(__file__).resolve().parents[1] / "models" / "all-MiniLM-L6-v2",
    )
)


class Scorer:
    """The active similarity method (camayoc-b6h).

    Embeddings were always the bead's intent; the deterministic matcher shipped
    because the weights are unreachable (403 on CONNECT from the CDN, re-tested
    2026-08-18 and still blocked at the proxy). This class is the seam: it
    selects a scorer at construction and **reports which one ran**, so the day
    weights land nothing about the discipline changes — only the label and the
    numbers.

    The label and the `semantic` flag are derived from the SAME decision that
    picks the scoring function. They cannot disagree, which is the point: a
    verdict claiming `semantic: true` while word-overlap produced the number is
    the exact masquerade this file exists to prevent, and keeping them as
    independent constants is how that happens.
    """

    def __init__(self, model_dir: Path | None = None):
        self._embedder = self._try_load(model_dir or MODEL_DIR)

    @staticmethod
    def _try_load(model_dir: Path):
        """Load an embedding model, or return None.

        Returns None on ANY failure — absent weights, absent runtime, a corrupt
        file. Never raises: a missing model must degrade to the lexical scorer
        with an honest label, not take down a coverage report. What it must
        never do is silently keep the embedding label.
        """
        weights = model_dir / "onnx" / "model.onnx"
        tokenizer = model_dir / "tokenizer.json"
        if not (weights.is_file() and tokenizer.is_file()):
            return None
        try:  # pragma: no cover - requires weights that are unavailable here
            import onnxruntime  # noqa: F401
            from tokenizers import Tokenizer

            return (onnxruntime.InferenceSession(str(weights)), Tokenizer.from_file(str(tokenizer)))
        except Exception:  # pragma: no cover - defensive
            return None

    @property
    def semantic(self) -> bool:
        return self._embedder is not None

    @property
    def method(self) -> str:
        return EMBEDDING_METHOD if self.semantic else LEXICAL_METHOD

    def score(self, asked: str, question: "Question") -> float:
        if self._embedder is None:
            return lexical_score(asked, question)
        return self._embedding_score(asked, question)  # pragma: no cover - no weights

    def _embedding_score(self, asked: str, question: "Question") -> float:  # pragma: no cover
        session, tokenizer = self._embedder
        a = self._embed(session, tokenizer, asked)
        b = self._embed(session, tokenizer, question.text)
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return 0.0 if na == 0 or nb == 0 else dot / (na * nb)

    @staticmethod
    def _embed(session, tokenizer, text: str) -> list[float]:  # pragma: no cover
        enc = tokenizer.encode(text)
        ids = [enc.ids]
        mask = [enc.attention_mask]
        feeds = {i.name: ids if "ids" in i.name else mask for i in session.get_inputs()}
        out = session.run(None, feeds)[0][0]
        # Mean-pool over tokens, masked.
        kept = [tok for tok, m in zip(out, enc.attention_mask) if m]
        if not kept:
            return []
        return [sum(vals) / len(kept) for vals in zip(*kept)]


#: Back-compat: the module-level METHOD names the scorer that runs by default.
METHOD = Scorer().method

#: Defaults. **Uncalibrated, and that is a statement not an apology**: there is
#: no held-out set of asked-questions-with-known-coverage to fit them against,
#: and inventing one by picking numbers that make today's examples come out
#: right would be fitting to the test rather than to the task. They are starting
#: points; every verdict carries the values actually used so a reader can
#: re-score with their own and compare.
#:
#: One consequence worth knowing before trusting a Full: Jaccard is symmetric,
#: so a competency question with a long trailing parenthetical is diluted by
#: words the asker never said — even a verbatim quote of it may land in Partial.
#: The bias is toward reporting a gap, which is the safe direction.
FLOOR = 0.12
FULL = 0.34


@dataclass
class Question:
    """One competency question, with where it came from."""

    id: str
    number: int
    text: str
    section: str
    source: str
    line: int
    parameters: list[str] = field(default_factory=list)

    def tokens(self) -> set[str]:
        return tokenize(self.text)


def tokenize(text: str) -> set[str]:
    """Words that carry meaning, with parameter placeholders stripped.

    `<work-item>` is a slot, not a word: leaving it in would score two unrelated
    questions as similar for sharing a parameter name.
    """
    text = PARAMETER.sub(" ", text)
    words = re.findall(r"[a-z][a-z0-9_-]*", text.lower())
    return {w for w in words if w not in NOISE and len(w) > 2}


def parse_file(path: Path) -> list[Question]:
    questions: list[Question] = []
    section = ""
    pending: Question | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            pending.text = " ".join(pending.text.split())
            pending.parameters = sorted(set(PARAMETER.findall(pending.text)))
            questions.append(pending)
            pending = None

    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        heading = HEADING.match(raw)
        if heading:
            flush()
            section = heading.group(1).strip()
            continue

        if any(skip in section.lower() for skip in NON_QUESTION_SECTIONS):
            continue

        item = ITEM.match(raw)
        if item:
            flush()
            number = int(item.group(1))
            pending = Question(
                id=f"{path.stem}#{number}",
                number=number,
                text=item.group(2),
                section=section,
                source=path.name,
                line=lineno,
            )
            continue

        # A continuation line: indented, non-blank, and we are inside an item.
        if pending is not None:
            if raw.strip() and raw[:1].isspace():
                pending.text += " " + raw.strip()
            elif not raw.strip():
                flush()

    flush()
    return questions


def parse_suite(directory: Path) -> list[Question]:
    suite: list[Question] = []
    for path in sorted(directory.glob("*.md")):
        suite.extend(parse_file(path))
    return suite


def watermark(suite: list[Question]) -> str:
    """A digest of the suite a verdict was computed against.

    Without it, a stored verdict cannot be told apart from one scored against a
    suite that has since gained the very question it reported missing.
    """
    digest = hashlib.sha256()
    for question in sorted(suite, key=lambda q: q.id):
        digest.update(f"{question.id}\x00{question.text}\x00".encode())
    return f"sha256:{digest.hexdigest()[:16]}"


def lexical_score(asked: str, question: Question) -> float:
    """Jaccard overlap of meaning-bearing words. Not semantic. See METHOD."""
    left, right = tokenize(asked), question.tokens()
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


#: Kept as the historical name; `Scorer` selects between this and embeddings.
score = lexical_score


def assess(
    asked: str,
    suite: list[Question],
    floor: float = FLOOR,
    full: float = FULL,
    top: int = 3,
    scorer: "Scorer | None" = None,
) -> dict:
    """Score one incoming question against the suite and classify its coverage.

    The verdict's `method` and `semantic` fields come from the scorer that
    actually ran, not from a module constant — so they cannot describe a
    scorer other than the one that produced the number.
    """
    scorer = scorer or Scorer()
    ranked = sorted(
        ((scorer.score(asked, q), q) for q in suite), key=lambda pair: (-pair[0], pair[1].id)
    )
    best = ranked[0][0] if ranked else 0.0

    if best >= full:
        coverage = "Full"
    elif best >= floor:
        coverage = "Partial"
    else:
        coverage = "Empty"

    return {
        "asked": asked,
        "coverage": coverage,
        "best_score": round(best, 4),
        # Everything needed to re-read this verdict later, or to distrust it.
        "method": scorer.method,
        "semantic": scorer.semantic,
        "floor": floor,
        "full": full,
        "suite_size": len(suite),
        "corpus_watermark": watermark(suite),
        "matches": [
            {"id": q.id, "score": round(s, 4), "text": q.text, "source": q.source}
            for s, q in ranked[:top]
            if s > 0
        ],
        "gap": coverage == "Empty",
    }


def gap_bead(verdict: dict) -> str:
    """The bead text a reported gap becomes. b6h: gaps become candidate questions."""
    return (
        f'bd create "Competency gap: {verdict["asked"]}" -t task -p P3 -l pitch\n'
        f"# no competency question covers this "
        f"(best {verdict['best_score']} by {verdict['method']}, floor {verdict['floor']}).\n"
        f"# scored against {verdict['corpus_watermark']}, {verdict['suite_size']} questions.\n"
        f"# NOT a semantic match — word overlap only. Re-check when embeddings land."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("question", nargs="?", help="the incoming question to assess")
    ap.add_argument("--suite", default="competency", help="directory of competency md files")
    ap.add_argument("--list", action="store_true", help="print the parsed suite and exit")
    ap.add_argument("--json", action="store_true", help="machine-readable verdict")
    ap.add_argument("--floor", type=float, default=FLOOR)
    ap.add_argument("--full", type=float, default=FULL)
    args = ap.parse_args()

    directory = Path(args.suite)
    if not directory.is_dir():
        print(f"no such suite directory: {directory}", file=sys.stderr)
        return 1

    suite = parse_suite(directory)
    if not suite:
        print(f"no competency questions parsed from {directory}", file=sys.stderr)
        return 1

    if args.list:
        if args.json:
            print(json.dumps([asdict(q) for q in suite], indent=2))
        else:
            print(f"{len(suite)} questions, {watermark(suite)}")
            for question in suite:
                params = f"  [{', '.join(question.parameters)}]" if question.parameters else ""
                print(f"  {question.id:<34} {question.text[:76]}{params}")
        return 0

    if not args.question:
        ap.error("a question is required unless --list is given")

    verdict = assess(args.question, suite, floor=args.floor, full=args.full)

    if args.json:
        print(json.dumps(verdict, indent=2))
        return 0

    print(f"coverage: {verdict['coverage']}   best {verdict['best_score']}")
    print(f"method:   {verdict['method']} — WORD OVERLAP, not semantic similarity")
    print(f"corpus:   {verdict['suite_size']} questions, {verdict['corpus_watermark']}")
    if verdict["matches"]:
        print("\nnearest:")
        for match in verdict["matches"]:
            print(f"  {match['score']:.3f}  {match['id']:<34} {match['text'][:66]}")

    if verdict["gap"]:
        print(
            "\nNO COVERAGE — no competency question reaches the floor. This is an\n"
            "ontology gap reported as its own outcome, NOT an answer from the nearest\n"
            "term. File it:\n"
        )
        print(gap_bead(verdict))
    elif verdict["coverage"] == "Partial":
        print(
            "\nPartial — related questions exist, none of them answers this. A candidate\n"
            "for a new competency question rather than a term stretched to fit."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
