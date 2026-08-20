"""The gate proof has to be able to FAIL — camayoc-045.

Before this file the untagged-write and falsifier refusals were proven only by
`scripts/bootstrap.sh` probes, which is to say: proven only on a machine that
had already installed a quipu, by a script nobody ran in CI, using a grep that
could not tell a refusal from a network error.

A gate that has never been observed to say no is not a gate. So each test here
stands up a stub store that behaves in one specific way and asserts what the
probe concludes. Two of the arms are regressions for defects the old grep
actually had:

  * `test_a_gateway_error_page_is_not_a_refusal` — a proxy answering 502 with
    "connect() failed (111: Connection refused) while connecting to upstream"
    matched the old alternation on "refus". The store was never reached, and
    the old arm printed PROVEN and exited 0. Verified against the old code.

    camayoc-045 attributes this to curl's stderr being captured by `2>&1`.
    That is wrong: `curl -s` prints no error message (exit 7, zero bytes on
    stderr), so a bare dead server did not trigger it. The response body is
    the path that does. `test_a_server_that_is_down_is_not_a_proof` covers the
    dead server anyway, because the old arm still mis-reported it — as "the
    store ACCEPTED", with a remedy about validate_on_write that has nothing to
    do with a socket that would not open.

  * `test_an_echoed_probe_is_not_a_violation` — the falsifier arm's grep
    alternation included the word "falsifier", and the probe body it sends
    contains that word twice. A store that ACCEPTED the write and echoed the
    node back read as PROVEN. Verified against the old code.

Both now fail loudly, and for the right reason: the verdict is read out of
designated JSON fields and the HTTP status, never out of text the caller
partly wrote.

The stub is deliberately not a quipu. Testing against a real store would prove
the shapes; these tests prove the PROBE, which is the thing that was never
tested and the thing that was wrong. `tests/test_metrics_slice.py` covers the
real-server path when a `quipu-server` binary is available.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_PROBE = ROOT / "scripts" / "gate_probe.sh"

#: Exit codes gate_probe.sh promises. Named here because the whole point of
#: camayoc-045 is that these three outcomes are different things.
REFUSED, ACCEPTED, NO_VERDICT = 0, 2, 3


class StubStore(BaseHTTPRequestHandler):
    """Answers /episode however the test class asked for. Set by subclassing."""

    status = 200
    payload: object = {"conforms": True, "id": "urn:accepted"}
    echo = False

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        request = self.rfile.read(length)

        payload = self.payload
        if self.echo:
            # The failure mode defect (b) describes: a store that took the
            # write and hands the node straight back, words and all.
            payload = dict(payload)  # type: ignore[arg-type]
            payload["node"] = json.loads(request)["nodes"][0]

        body = json.dumps(payload).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def run_probes(server_url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(GATE_PROBE)],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "QUIPU_SERVER": server_url},
        capture_output=True,
        text=True,
        timeout=120,
    )


class ProbeBehaviourTests(unittest.TestCase):
    """One stub store per test; the assertion is what the probe concluded."""

    def probe_against(self, **behaviour) -> subprocess.CompletedProcess:
        handler = type("Handler", (StubStore,), behaviour)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            return run_probes(f"http://127.0.0.1:{server.server_port}")
        finally:
            server.shutdown()
            server.server_close()

    # ------------------------------------------------------------- the gate works
    def test_a_shacl_violation_report_proves_the_gate(self):
        result = self.probe_against(
            payload={
                "conforms": False,
                "violations": [
                    {"message": "sourceKind is required"},
                    {"message": "falsifier is required"},
                    {"message": "repositorySource is required"},
                    {"message": "blockerEvidence is required"},
                ],
            }
        )
        self.assertEqual(REFUSED, result.returncode, result.stdout + result.stderr)
        self.assertEqual(len(probes()), result.stdout.count("PROVEN"))
        self.assertNotIn("NOT PROVEN", result.stdout)

    def test_quipus_real_shacl_failure_body_proves_the_gate(self):
        """The shape quipu actually returns, rather than a generic SHACL report.

        `violations` is a COUNT and `issues` is the list (src/mcp/mod.rs:471-477),
        and it arrives with HTTP 200 — so a probe that keyed off the status line
        or read `violations` as a list would get this wrong in both directions.
        """
        result = self.probe_against(
            payload={
                "conforms": False,
                "violations": 1,
                "warnings": 0,
                "issues": [{"message": "sourceKind is required"}],
                "hint": "tag the node",
            }
        )
        self.assertEqual(REFUSED, result.returncode, result.stdout + result.stderr)
        self.assertEqual(len(probes()), result.stdout.count("PROVEN"))
        self.assertNotIn("NOT PROVEN", result.stdout)

    def test_a_violation_count_alone_is_a_refusal(self):
        """No detail list, just a nonzero count. Still a no."""
        result = self.probe_against(payload={"conforms": False, "violations": 2})
        self.assertEqual(REFUSED, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("NOT PROVEN", result.stdout)

    def test_a_4xx_decline_proves_the_gate_without_a_violation_body(self):
        """Not every store returns a SHACL report. A refusal is still a refusal."""
        result = self.probe_against(status=422, payload={"error": "validation failed"})
        self.assertEqual(REFUSED, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("NOT PROVEN", result.stdout)

    # --------------------------------------------------------- the gate is off
    def test_an_accepted_write_is_reported_as_the_gate_being_off(self):
        result = self.probe_against(payload={"conforms": True, "id": "urn:took-it"})
        self.assertEqual(ACCEPTED, result.returncode, result.stdout + result.stderr)
        self.assertIn("NOT PROVEN", result.stdout)
        self.assertIn("ACCEPTED", result.stdout)

    def test_a_bare_success_with_no_verdict_field_is_still_acceptance(self):
        """HTTP 200 and nothing that says no means the write landed."""
        result = self.probe_against(payload={"nodes": ["camayoc-gate-probe"]})
        self.assertEqual(ACCEPTED, result.returncode, result.stdout + result.stderr)
        self.assertIn("NOT PROVEN", result.stdout)

    # ------------------------------------------ regression: defect (b), echoing
    def test_an_echoed_probe_is_not_a_violation(self):
        """The store ACCEPTS and echoes the node back, name and description.

        Every word the old alternation searched for — falsifier, sourceKind,
        repositorySource, blockerEvidence — is in what comes back, because the
        probe put it there. The verdict must come from the verdict fields.
        """
        result = self.probe_against(payload={"conforms": True, "id": "urn:took-it"}, echo=True)
        self.assertEqual(ACCEPTED, result.returncode, result.stdout + result.stderr)
        self.assertIn("NOT PROVEN", result.stdout)

        # The probes must really carry the words they are named for, or the
        # echo above sends nothing incriminating back and this proves nothing.
        probes = GATE_PROBE.read_text()
        for term in ("falsifier", "sourceKind", "repositorySource", "blockerEvidence"):
            self.assertIn(term, probes)

    # --------------------------------------- regression: defect (a), no server
    def test_a_server_that_is_down_is_not_a_proof(self):
        """A socket that will not open is not evidence about the shapes.

        The old arm called this "the store ACCEPTED an untagged Decision" and
        told the operator to enable validate_on_write. Both false, and the
        remedy sends them to the wrong file.
        """
        result = run_probes("http://127.0.0.1:1")
        self.assertEqual(NO_VERDICT, result.returncode, result.stdout + result.stderr)
        self.assertIn("NOT PROVEN", result.stdout)
        self.assertIn("could not look", result.stdout)
        self.assertNotIn("PROVEN —", result.stdout.replace("NOT PROVEN", ""))

    def test_a_server_fault_is_not_a_verdict(self):
        """A 500 means the write did not land. It does not mean the gate held."""
        result = self.probe_against(status=500, payload={"error": "internal"})
        self.assertEqual(NO_VERDICT, result.returncode, result.stdout + result.stderr)
        self.assertIn("could not look", result.stdout)

    def test_a_gateway_error_page_is_not_a_refusal(self):
        """The reachable form of defect (a): a proxy answers, the store does not.

        This is the exact page nginx serves when the upstream socket is closed.
        It contains "Connection refused", it arrives on stdout where `-s` does
        not suppress it, and the old alternation matched it — PROVEN, exit 0,
        having never reached the store at all.
        """

        class HtmlHandler(StubStore):
            def do_POST(self):
                body = (
                    b"<html><head><title>502 Bad Gateway</title></head><body>\n"
                    b"connect() failed (111: Connection refused) while connecting to upstream\n"
                    b"</body></html>"
                )
                self.send_response(502)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), HtmlHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = run_probes(f"http://127.0.0.1:{server.server_port}")
        finally:
            server.shutdown()
            server.server_close()
        # The page literally contains "refused"; the old grep took it (verified).
        self.assertEqual(NO_VERDICT, result.returncode, result.stdout + result.stderr)
        self.assertIn("could not look", result.stdout)


class ArmIndependenceTests(unittest.TestCase):
    """Each arm must be able to fail on its own.

    The arms are ordered and the script exits on the first failure, which is
    correct behaviour and also means a later arm can be dead code nobody
    notices. This drives each arm individually by trimming the ones before it.
    """

    ARMS = (
        "untagged Decision",
        "no falsifier",
        "no repository source",
        "no evidence kind",
        "no exemplar trajectory",
        "no authority",
        "no promoting principal",
    )

    def test_every_arm_reports_acceptance_when_it_is_the_first_to_run(self):
        source = GATE_PROBE.read_text()
        for index, label in enumerate(self.ARMS):
            with self.subTest(arm=label):
                # Make the earlier arms pass by turning their gate_arm calls into
                # no-ops, so the arm under test is the one that reaches the stub.
                script = source.replace(
                    "run_gate_probes() {",
                    "run_gate_probes() {\n  _skipped=0",
                    1,
                )
                for _ in range(index):
                    script = script.replace("  gate_arm ", "  : skipped ", 1)

                path = Path(self.temp) / f"arm{index}.sh"
                path.write_text(script)

                server = ThreadingHTTPServer(("127.0.0.1", 0), StubStore)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    result = subprocess.run(
                        ["bash", str(path)],
                        env={
                            "PATH": "/usr/bin:/bin:/usr/local/bin",
                            "QUIPU_SERVER": f"http://127.0.0.1:{server.server_port}",
                        },
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                finally:
                    server.shutdown()
                    server.server_close()

                self.assertEqual(ACCEPTED, result.returncode, result.stdout + result.stderr)
                self.assertIn(label, result.stdout)

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.temp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)


# ---------------------------------------------------------------------------
# camayoc-104: the arms must DISCRIMINATE, not merely run.
#
# ArmIndependenceTests above proves each arm is reachable and can report
# acceptance on its own. That is necessary and it is not the claim provisional D
# makes. D's claim is stronger: each probe omits EXACTLY ONE required property,
# so that a failure of one gate cannot make another look enforced. That is a
# claim about independence, and a green suite does not establish it — every test
# above passes just as happily if two probes violate the same shape.
#
# So the claim is attacked from both ends. Statically: read the shapes, read the
# probes, and assert the "exactly one" arithmetic holds. Dynamically: enforce
# one shape at a time and confirm only the matching arm flips.
# ---------------------------------------------------------------------------

SHAPES = ROOT / "shapes" / "core.shapes.ttl"

#: A node's `name` becomes its `rdfs:label`, so every probe satisfies the
#: mandatory-label constraint by construction. VERIFIED, not assumed, against
#: quipu's own test: src/episode/tests.rs:742 asserts
#: `active_values(store, "{ns}path-a", RDFS_LABEL) == ["path-a"]` for a node
#: written as `{"name": "path-a", ...}`. If that ever changes, every probe
#: violates two shapes at once and the static test below goes red — which is
#: the point of writing it down here rather than in a comment.
NAME_SUPPLIES_LABEL = "label"


def required_properties_by_class() -> dict[str, set[str]]:
    """Parse `sh:minCount 1` paths per `sh:targetClass` out of the shapes.

    Deliberately parsed from the shapes file rather than hardcoded: a hardcoded
    copy is a second source of truth that drifts, and drift here is invisible
    precisely because the suite stays green while it happens.
    """
    text = SHAPES.read_text()
    shapes: dict[str, set[str]] = {}
    for block in re.split(r"\n(?=aegis:\w+Shape a sh:NodeShape)", text):
        target = re.search(r"sh:targetClass aegis:(\w+)", block)
        if not target:
            continue
        required = set()
        for prop in re.finditer(r"sh:property\s*\[(.*?)\]\s*[;.]", block, re.S):
            body = prop.group(1)
            path = re.search(r"sh:path\s+(?:aegis:|rdfs:)(\w+)", body)
            if path and re.search(r"sh:minCount\s+1", body):
                required.add(path.group(1))
        shapes[target.group(1)] = required
    return shapes


def probes() -> list[tuple[str, dict]]:
    """The (expected-term, node) pairs the gate script actually sends.

    Read out of the script so the tests cannot drift from it.
    """
    source = GATE_PROBE.read_text()
    pattern = re.compile(r"gate_arm \"[^\"]+\" \"([^\"]+)\" '(\{.*?\})' \"", re.S)
    found = [(m.group(1), json.loads(m.group(2))["nodes"][0]) for m in pattern.finditer(source)]
    if not found:
        raise AssertionError("no gate_arm probes parsed — the script's shape changed")
    return found


def satisfied_properties(node: dict) -> set[str]:
    """Which required-property names this node supplies."""
    supplied = set(node.get("properties") or {})
    if node.get("name"):
        supplied.add(NAME_SUPPLIES_LABEL)
    return supplied


class ProbeDiscriminationTests(unittest.TestCase):
    """Static half: each probe omits exactly one required property."""

    def test_each_probe_omits_exactly_one_required_property(self):
        required = required_properties_by_class()
        for expected_term, node in probes():
            with self.subTest(arm=expected_term):
                node_type = node["type"]
                self.assertIn(
                    node_type, required,
                    f"{node_type} has no shape — the probe proves nothing",
                )
                missing = required[node_type] - satisfied_properties(node)
                self.assertEqual(
                    {expected_term}, missing,
                    f"the {expected_term} arm omits {sorted(missing)}. A probe that "
                    f"violates more than one shape cannot tell you which gate "
                    f"refused it; a probe that violates none cannot fail at all.",
                )

    def test_every_probe_targets_a_distinct_shape(self):
        """Two arms testing one shape would make the second redundant and, worse,
        would let one enforced shape report two gates as PROVEN."""
        terms = [term for term, _ in probes()]
        self.assertEqual(len(terms), len(set(terms)), f"duplicate arms: {terms}")

    def test_the_expected_term_is_actually_a_required_property_of_its_class(self):
        """Guards against an arm named for a property the shapes do not require —
        it would be refused for some other reason and still print PROVEN."""
        required = required_properties_by_class()
        for expected_term, node in probes():
            with self.subTest(arm=expected_term):
                self.assertIn(expected_term, required[node["type"]])


class SelectiveStore(StubStore):
    """A store enforcing EXACTLY ONE shape, so the arms can be told apart.

    Set `enforced` to a (class, property) pair. A node of that class missing
    that property is refused; everything else is accepted. This is the
    single-gate sabotage camayoc-104 asks for: break one gate, and only the
    matching probe may flip.
    """

    enforced: tuple[str, str] = ("", "")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        node = json.loads(self.rfile.read(length))["nodes"][0]
        target, prop = self.enforced

        supplied = set(node.get("properties") or {})
        if node.get("name"):
            supplied.add(NAME_SUPPLIES_LABEL)

        if node.get("type") == target and prop not in supplied:
            payload = {
                "conforms": False,
                "violations": 1,
                "issues": [{"message": f"camayoc: {prop} is required"}],
            }
        else:
            payload = {"conforms": True, "id": "urn:accepted"}

        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GateSabotageTests(unittest.TestCase):
    """Dynamic half: enforce one shape at a time; only its arm may flip.

    Every other test in this file runs against a store that answers the same way
    to all four probes, so none of them can distinguish "the gate works" from
    "something refuses everything". These can.
    """

    #: (class, required property) per arm, in the script's order.
    GATES = (
        ("Decision", "sourceKind"),
        ("Verification", "falsifier"),
        ("ExecutionPath", "repositorySource"),
        ("Blocker", "blockerEvidence"),
        ("GoldenPath", "prunedFrom"),
        ("PathOmission", "omissionAuthority"),
        ("PathPromotion", "promotedBy"),
    )

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.temp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.source = GATE_PROBE.read_text()

    def _script_starting_at(self, index: int) -> Path:
        """The gate script with the first `index` arms turned into no-ops.

        The script exits on the first failing arm, so driving arm N requires
        silencing the ones before it.
        """
        script = self.source
        for _ in range(index):
            script = script.replace("  gate_arm ", "  : skipped ", 1)
        path = Path(self.temp) / f"from{index}.sh"
        path.write_text(script)
        return path

    def _run(self, script: Path, enforced: tuple[str, str]):
        handler = type("Selective", (SelectiveStore,), {"enforced": enforced})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            return subprocess.run(
                ["bash", str(script)],
                env={
                    "PATH": "/usr/bin:/bin:/usr/local/bin",
                    "QUIPU_SERVER": f"http://127.0.0.1:{server.server_port}",
                },
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            server.shutdown()
            server.server_close()

    def test_a_single_enforced_shape_proves_only_its_own_arm(self):
        """The positive half: break gate i, and arm i reports PROVEN."""
        for index, gate in enumerate(self.GATES):
            with self.subTest(gate=gate):
                result = self._run(self._script_starting_at(index), gate)
                self.assertIn(
                    "PROVEN", result.stdout,
                    f"enforcing {gate} did not prove its own arm:\n{result.stdout}",
                )
                self.assertNotIn("NOT PROVEN", result.stdout.split("\n")[0])

    def test_an_enforced_shape_proves_no_other_arm(self):
        """The half that actually establishes independence.

        With gate i enforced, arm j (j != i) must report the store ACCEPTED —
        exit 2. If it reported PROVEN, then gate i's refusal would be standing
        in for gate j and a disabled gate j would look enforced. That is exactly
        the failure provisional D's "exactly one property" design exists to
        prevent, and nothing before this test could detect it.
        """
        for enforced_index, gate in enumerate(self.GATES):
            for arm_index, arm in enumerate(self.GATES):
                if arm_index == enforced_index:
                    continue
                with self.subTest(enforced=gate, arm=arm):
                    result = self._run(self._script_starting_at(arm_index), gate)
                    self.assertEqual(
                        ACCEPTED, result.returncode,
                        f"with only {gate} enforced, the {arm} arm did not report "
                        f"acceptance — it cannot distinguish its own gate from "
                        f"{gate}:\n{result.stdout}",
                    )

    def test_with_nothing_enforced_every_arm_reports_the_gate_is_off(self):
        """The floor. A store enforcing no shape must fail the very first arm —
        otherwise the suite above could be passing against a store that refuses
        for reasons unrelated to the shapes."""
        result = self._run(self._script_starting_at(0), ("Nothing", "nothing"))
        self.assertEqual(ACCEPTED, result.returncode, result.stdout)
        self.assertIn("NOT PROVEN", result.stdout)


if __name__ == "__main__":
    sys.exit(unittest.main())
