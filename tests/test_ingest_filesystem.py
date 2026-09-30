"""Filesystem exports enter as governed FileCollections, under the writer's gates."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "ingest_filesystem", ROOT / "scripts/ingest_filesystem.py"
)
fs = importlib.util.module_from_spec(spec)
sys.modules["ingest_filesystem"] = fs  # dataclasses resolve their module by name
assert spec.loader
spec.loader.exec_module(fs)

MTIME = 1_750_000_000  # 2025-06-15T15:06:40Z


def write(path: Path, size: int, mtime: int = MTIME) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))


def tree(root: Path) -> None:
    """SHOWS-like: show/season/episode, plus a deep ROM three folders down."""
    write(root / "Show A" / "Season 1" / "e1.MKV", 10)
    write(root / "Show A" / "Season 1" / "e2.mkv", 20, MTIME + 60)
    write(root / "Show A" / "Season 2" / "e1.mkv", 30)
    write(root / "Show A" / "poster.jpg", 5)
    write(root / "Games" / "n64" / "carts" / "deep" / "GoldenEye.z64", 7)
    write(root / "Games" / ".hidden", 1)
    write(root / "README", 2)


class CrawlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "share"
        tree(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_aggregates_are_per_subtree_and_stop_at_depth(self):
        result = fs.crawl(str(self.root), 2)
        self.assertEqual([], result.errors)
        self.assertEqual(
            {"", "Games", "Games/n64", "Show A", "Show A/Season 1", "Show A/Season 2"},
            set(result.collections),
        )
        top = result.collections[""]
        self.assertEqual((7, 75), (top.files, top.bytes))
        show = result.collections["Show A"]
        self.assertEqual((4, 65), (show.files, show.bytes))
        self.assertEqual(MTIME + 60, show.newest)
        # A file BELOW the depth limit still counts in every ancestor.
        self.assertEqual(1, result.collections["Games/n64"].exts[".z64"])
        self.assertEqual(1, top.exts[".z64"])

    def test_extensions_are_lowercased_and_dotfiles_have_none(self):
        exts = fs.crawl(str(self.root), 0).collections[""].exts
        self.assertEqual(3, exts[".mkv"])  # e1.MKV folds into .mkv
        self.assertEqual(2, exts[fs.NO_EXT])  # .hidden and README
        self.assertEqual(fs.OTHER_EXT, fs.extension_of("a.this-is-far-too-long-ext"))

    def test_symlinks_are_not_followed_or_counted(self):
        outside = Path(self.tmp.name) / "outside"
        write(outside / "big.iso", 1000)
        os.symlink(outside, self.root / "link-dir")
        os.symlink(outside / "big.iso", self.root / "link-file.iso")
        top = fs.crawl(str(self.root), 1).collections[""]
        self.assertEqual((7, 75), (top.files, top.bytes))
        self.assertNotIn(".iso", top.exts)
        self.assertNotIn("link-dir", fs.crawl(str(self.root), 1).collections)

    @unittest.skipIf(os.geteuid() == 0, "root reads everything")
    def test_an_unreadable_folder_is_an_error_not_a_silent_undercount(self):
        locked = self.root / "Show A" / "Season 2"
        locked.chmod(0)
        try:
            result = fs.crawl(str(self.root), 1)
        finally:
            locked.chmod(0o755)
        self.assertEqual(1, len(result.errors))
        self.assertIn("Show A/Season 2", result.errors[0])

    def test_the_crawl_opens_no_file_and_writes_nothing(self):
        before = sorted((p, p.stat().st_mtime_ns) for p in self.root.rglob("*"))
        fs.crawl(str(self.root), 3)
        after = sorted((p, p.stat().st_mtime_ns) for p in self.root.rglob("*"))
        self.assertEqual(before, after)


class EpisodeTests(unittest.TestCase):
    EXPORT = {"path": "/pool/media", "mount": "/unused", "depth": 2,
              "description": "nas:/pool/media"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "share"
        tree(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def body(self, export=None):
        export = export or self.EXPORT
        return fs.episode_for("nas", export, fs.crawl(str(self.root), export["depth"]),
                              actor="ian")

    def test_names_are_safe_stable_and_keyed_per_export(self):
        body = self.body()
        self.assertEqual("fs-export:nas:/pool/media", body["name"])
        self.assertTrue(body["replace_snapshot"])
        self.assertEqual(fs.planes.plane_for("observed"), body["graph"])
        for node in body["nodes"]:
            self.assertRegex(node["name"], r"^[A-Za-z0-9._-]+$")
        export = body["nodes"][0]
        self.assertEqual(("nas__pool_media", "NFSExport"), (export["name"], export["type"]))
        self.assertEqual(fs.collection_name("nas__pool_media", "Show A/Season 1"),
                         fs.collection_name("nas__pool_media", "Show A/Season 1"))
        self.assertNotEqual(fs.collection_name("nas__pool_media", "a/b"),
                            fs.collection_name("nas__pool_media", "a_b"))

    def test_a_rerun_over_an_unchanged_tree_is_byte_identical(self):
        first = json.dumps(self.body(), sort_keys=True)
        second = json.dumps(self.body(), sort_keys=True)
        self.assertEqual(first, second)
        self.assertNotIn(str(self.tmp.name), first, "the crawl root must not leak in")

    def test_collections_carry_the_governed_properties(self):
        body = self.body()
        by_rel = {n["properties"]["relativePath"]: n for n in body["nodes"]
                  if n["type"] == "FileCollection"}
        games = by_rel["Games"]["properties"]
        self.assertEqual([".z64"], games["hasExtension"])
        self.assertEqual("2025-06-15T15:06:40Z", games["newestMtime"])
        self.assertEqual(2, games["fileCount"])
        self.assertEqual("nas:/pool/media/Games", by_rel["Games"]["description"])
        root = by_rel["."]["properties"]
        for ext in root["hasExtension"]:
            self.assertRegex(ext, fs.EXT_RE.pattern)
        self.assertNotIn(fs.NO_EXT, root["hasExtension"])
        self.assertIn("(none)=2", root["extensionCounts"])

    def test_edges_link_every_collection_to_its_export_and_parent(self):
        body = self.body()
        ent = "nas__pool_media"
        season = fs.collection_name(ent, "Show A/Season 1")
        edges = {(e["source"], e["relation"], e["target"]) for e in body["edges"]}
        self.assertIn((season, "inExport", ent), edges)
        self.assertIn((season, "parentCollection", fs.collection_name(ent, "Show A")), edges)
        self.assertIn((fs.collection_name(ent, "Show A"), "parentCollection",
                       fs.collection_name(ent, "")), edges)
        self.assertEqual(0, sum(1 for s, r, _ in edges
                                if s == fs.collection_name(ent, "") and r == "parentCollection"))

    def test_a_reference_only_export_is_linked_not_re_emitted(self):
        body = self.body({**self.EXPORT, "reference_only": True})
        self.assertNotIn("NFSExport", [n["type"] for n in body["nodes"]])
        self.assertIn("nas__pool_media", {e["target"] for e in body["edges"]})

    def test_an_uncrawled_export_is_modelled_with_no_collections(self):
        body = fs.episode_for("nas", {"path": "/pool/raw", "mount": None}, None, actor="ian")
        self.assertEqual(["NFSExport"], [n["type"] for n in body["nodes"]])
        self.assertEqual([], body["edges"])


class RootChecks(unittest.TestCase):
    def test_empty_and_missing_roots_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(fs.FsExportError, "empty"):
                fs.check_root({"path": "/p", "mount": tmp}, require_mountpoint=False)
            with self.assertRaisesRegex(fs.FsExportError, "not a directory"):
                fs.check_root({"path": "/p", "mount": tmp + "/nope"}, require_mountpoint=False)
            write(Path(tmp) / "f", 1)
            with self.assertRaisesRegex(fs.FsExportError, "not a mountpoint"):
                fs.check_root({"path": "/p", "mount": tmp}, require_mountpoint=True)
            fs.check_root({"path": "/p", "mount": tmp}, require_mountpoint=False)


class FakeStore:
    """Scripted gate readings; records every post and sleep."""

    def __init__(self, memory, versions=None, prior=0):
        self.memory_seq = list(memory)
        self.versions = list(versions or ["v1"] * len(self.memory_seq))
        self.prior = prior
        self.posts, self.sleeps, self.logs = [], [], []

    def gates(self, **kw):
        def memory():
            value = self.memory_seq.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        return fs.Gates(memory=memory, version=lambda: self.versions.pop(0),
                        prior_count=lambda ent: self.prior, sleep=self.sleeps.append, **kw)

    def post(self, body):
        self.posts.append(body)
        return {"outcome": "created", "count": 3}

    def run(self, bodies, **kw):
        return fs.post_snapshots(bodies, self.gates(**kw), self.post, self.logs.append)


def bodies(n, shrink=None):
    out = [{"name": f"fs-export:nas:/e{i}", "nodes": []} for i in range(n)]
    if shrink:
        out[0]["_shrink_check"] = shrink
    return out


class GateTests(unittest.TestCase):
    def test_all_snapshots_written_sequentially_and_paced(self):
        store = FakeStore([1e9] * 4)
        self.assertEqual(fs.EXIT_OK, store.run(bodies(3)))
        self.assertEqual(3, len(store.posts))
        self.assertEqual([fs.MIN_PACE_S] * 2, store.sleeps)
        self.assertTrue(all(not k.startswith("_") for p in store.posts for k in p))

    def test_an_unanswerable_memory_probe_writes_nothing(self):
        store = FakeStore([fs.GateUnknown("prometheus down")])
        self.assertEqual(fs.EXIT_UNKNOWN, store.run(bodies(2)))
        self.assertEqual([], store.posts)

    def test_memory_at_the_skip_line_skips_the_whole_run(self):
        store = FakeStore([4.0e9])
        self.assertEqual(fs.EXIT_SKIPPED, store.run(bodies(2)))
        self.assertEqual([], store.posts)
        self.assertEqual("skip", store.logs[-1]["gate"])
        # CONTROL: one byte under the line runs.
        self.assertEqual(fs.EXIT_OK, FakeStore([4.0e9 - 1] * 3).run(bodies(2)))

    def test_memory_reaching_the_abort_line_stops_between_snapshots(self):
        store = FakeStore([1e9, 1e9, 5.0e9])
        self.assertEqual(fs.EXIT_ABORTED, store.run(bodies(3)))
        self.assertEqual(1, len(store.posts))
        self.assertEqual(["fs-export:nas:/e0"], store.logs[-1]["written"])

    def test_a_store_version_change_mid_run_aborts(self):
        store = FakeStore([1e9] * 3, versions=["v1", "v1", "v2"])
        self.assertEqual(fs.EXIT_ABORTED, store.run(bodies(2)))
        self.assertEqual(1, len(store.posts))
        self.assertIn("version", store.logs[-1]["reason"])

    def test_a_crawl_that_shrank_too_far_is_refused(self):
        store = FakeStore([1e9] * 2, prior=100)
        self.assertEqual(fs.EXIT_ERROR, store.run(bodies(1, shrink=("nas__e0", 49))))
        self.assertEqual([], store.posts)
        # CONTROL: at exactly half it writes.
        store = FakeStore([1e9] * 2, prior=100)
        self.assertEqual(fs.EXIT_OK, store.run(bodies(1, shrink=("nas__e0", 50))))

    def test_a_failed_post_stops_the_run_and_says_indeterminate(self):
        store = FakeStore([1e9] * 3)

        def post(body):
            raise TimeoutError("timed out")

        rc = fs.post_snapshots(bodies(2), store.gates(), post, store.logs.append)
        self.assertEqual(fs.EXIT_ERROR, rc)
        self.assertIn("INDETERMINATE", store.logs[-1]["note"])


class Completed:
    def __init__(self, stdout, returncode=0):
        self.stdout, self.returncode = stdout, returncode


class UnitMemoryTests(unittest.TestCase):
    def test_reads_memory_current(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return Completed("4674990080\n")

        self.assertEqual(4674990080.0, fs.unit_memory("quipu.service", run=run))
        self.assertEqual(["systemctl", "show", "-p", "MemoryCurrent", "--value",
                          "quipu.service"], calls[0])

    def test_not_set_is_unknown_not_zero(self):
        # systemd answers an unknown unit with "[not set]" and exit 0.
        with self.assertRaises(fs.GateUnknown):
            fs.unit_memory("nope.service", run=lambda *a, **k: Completed("[not set]\n"))
        with self.assertRaises(fs.GateUnknown):
            fs.unit_memory("quipu.service", run=lambda *a, **k: Completed("", 1))

    def test_only_a_service_name_is_accepted(self):
        with self.assertRaises(fs.GateUnknown):
            fs.unit_memory("--all", run=lambda *a, **k: Completed("1"))

    def test_both_probes_configured_is_ambiguous(self):
        cfg = Path(tempfile.mkdtemp()) / "c.json"
        cfg.write_text(json.dumps({"host": "nas", "exports": [{"path": "/p", "mount": None}]}))
        env = {fs.MEMORY_UNIT_ENV: "quipu.service", fs.PROM_URL_ENV: "http://p",
               fs.MEMORY_QUERY_ENV: "q"}
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            self.assertEqual(fs.EXIT_UNKNOWN,
                             fs.main(["--config", str(cfg), "--actor", "ian", "--post"]))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        tree(self.dir / "share")
        self.config = self.dir / "fs.json"
        self.config.write_text(json.dumps({"host": "nas", "exports": [
            {"path": "/pool/media", "mount": str(self.dir / "share"), "depth": 1},
            {"path": "/pool/raw", "mount": None},
        ]}))

    def tearDown(self):
        self.tmp.cleanup()

    def main(self, *extra):
        return fs.main(["--config", str(self.config), "--actor", "ian",
                        "--no-mountpoint-check", *extra])

    def test_offline_run_writes_only_out(self):
        out = self.dir / "out"
        self.assertEqual(fs.EXIT_OK, self.main("--out", str(out)))
        self.assertEqual(2, len(list(out.glob("*.json"))))

    def test_pace_below_the_minimum_is_refused_before_any_gate(self):
        self.assertEqual(fs.EXIT_ERROR, self.main("--post", "--pace", "5"))

    def test_post_without_a_memory_probe_is_unknown(self):
        env = {k: os.environ.pop(k, None)
               for k in (fs.PROM_URL_ENV, fs.MEMORY_QUERY_ENV, fs.MEMORY_UNIT_ENV)}
        try:
            self.assertEqual(fs.EXIT_UNKNOWN, self.main("--post"))
        finally:
            os.environ.update({k: v for k, v in env.items() if v is not None})

    def test_an_unmounted_root_refuses_every_snapshot(self):
        cfg = json.loads(self.config.read_text())
        cfg["exports"][0]["mount"] = str(self.dir / "empty")
        (self.dir / "empty").mkdir()
        self.config.write_text(json.dumps(cfg))
        self.assertEqual(fs.EXIT_ERROR, self.main())

    @unittest.skipIf(os.geteuid() == 0, "root reads everything")
    def test_a_crawl_with_unreadable_entries_is_refused_unless_allowed(self):
        locked = self.dir / "share" / "Show A"
        locked.chmod(0)
        try:
            self.assertEqual(fs.EXIT_ERROR, self.main())
            # CONTROL: the explicit override writes (offline) the undercount.
            self.assertEqual(fs.EXIT_OK, self.main("--allow-errors"))
        finally:
            locked.chmod(0o755)

    def test_config_refuses_relative_and_duplicate_paths(self):
        for exports in ([{"path": "rel"}], [{"path": "/a"}, {"path": "/a"}]):
            self.config.write_text(json.dumps({"host": "nas", "exports": exports}))
            self.assertEqual(fs.EXIT_ERROR, self.main())


if __name__ == "__main__":
    unittest.main()
