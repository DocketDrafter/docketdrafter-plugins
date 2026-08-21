#!/usr/bin/env python3
"""Unit tests for the correctness-critical parts of the CourtListener library.

Run with: python3 tools/courtlistener/test_courtlistener.py

Deliberately stdlib-only (unittest, no pytest) so it runs anywhere the server
runs. The citation tests are regressions for a bug that returned a *different*
case than the one asked for and reported it as a cache hit.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_DIR = REPO_ROOT / "plugins" / "courtlistener" / "mcp"
sys.path.insert(0, str(MCP_DIR / "lib"))
sys.path.insert(0, str(MCP_DIR / "vendor"))

from courtlistener_mcp.courts import get_court, require_court, search_courts  # noqa: E402
from courtlistener_mcp.sources.courtlistener import (  # noqa: E402
    _saved_citations,
    find_saved_by_citation,
    read_metadata,
)
from courtlistener_mcp.text import sanitize_filename  # noqa: E402
from courtlistener_mcp import http  # noqa: E402


def save_case(root: Path, case_id: str, metadata: dict) -> Path:
    case_dir = root / case_id
    case_dir.mkdir(parents=True)
    (case_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (case_dir / "opinion.md").write_text("body", encoding="utf-8")
    (case_dir / "opinion.html").write_text("<p>body</p>", encoding="utf-8")
    return case_dir


def save_legacy_case(root: Path, case_id: str, metadata: dict) -> Path:
    """A case as the retired script-based skill wrote it: metadata.yaml only."""
    case_dir = root / case_id
    case_dir.mkdir(parents=True)
    lines = []
    for key, value in metadata.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f'  - "{item}"' for item in value)
        else:
            lines.append(f'{key}: "{value}"')
    (case_dir / "metadata.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (case_dir / "opinion.md").write_text("body", encoding="utf-8")
    (case_dir / "opinion.html").write_text("<p>body</p>", encoding="utf-8")
    return case_dir


class CitationMatching(unittest.TestCase):
    """A saved case must only match its own citations."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        save_case(
            self.root,
            "cl-999-unrelated",
            {
                "case_name": "Unrelated v. Other",
                "citations": ["5 F.3d 100"],
                "lookup_citation": "",
                "source_url": "https://www.courtlistener.com/opinion/999/unrelated/",
            },
        )

    def test_exact_citation_matches(self) -> None:
        found = find_saved_by_citation("5 F.3d 100", self.root)
        self.assertIsNotNone(found)
        self.assertEqual(found.description, "Unrelated v. Other")
        self.assertEqual(found.status, "already_saved")

    def test_citation_is_whitespace_and_case_insensitive(self) -> None:
        self.assertIsNotNone(find_saved_by_citation("  5  f.3d   100 ", self.root))

    def test_numeric_prefix_does_not_match(self) -> None:
        """'5 F.3d 1' must not resolve to the case at '5 F.3d 100'."""
        for query in ("5 F.3d 1", "5 F.3d 10"):
            with self.subTest(query=query):
                self.assertIsNone(find_saved_by_citation(query, self.root))

    def test_reporter_alone_does_not_match(self) -> None:
        self.assertIsNone(find_saved_by_citation("F.3d", self.root))

    def test_case_name_does_not_match_as_citation(self) -> None:
        self.assertIsNone(find_saved_by_citation("Unrelated", self.root))

    def test_empty_citation_does_not_match(self) -> None:
        self.assertIsNone(find_saved_by_citation("   ", self.root))

    def test_incomplete_case_is_ignored(self) -> None:
        partial = self.root / "cl-1000-partial"
        partial.mkdir()
        (partial / "metadata.json").write_text(
            json.dumps({"citations": ["1 U.S. 1"]}), encoding="utf-8"
        )
        self.assertIsNone(find_saved_by_citation("1 U.S. 1", self.root))

    def test_lookup_citation_is_matchable(self) -> None:
        save_case(
            self.root,
            "cl-1001-lookup",
            {"case_name": "By Lookup", "citations": [], "lookup_citation": "9 Cal.4th 55"},
        )
        found = find_saved_by_citation("9 Cal.4th 55", self.root)
        self.assertIsNotNone(found)
        self.assertEqual(found.description, "By Lookup")


class ClusterIdLookup(unittest.TestCase):
    """Cluster lookup must be exact — cl-123 must never match cl-1234-*."""

    def test_prefix_cluster_id_does_not_match(self) -> None:
        from courtlistener_mcp.sources.courtlistener import find_saved_by_cluster_id

        root = Path(tempfile.mkdtemp())
        save_case(root, "cl-1234-other-case", {"case_name": "Other v. Case", "citations": []})
        self.assertIsNone(find_saved_by_cluster_id(123, root))
        found = find_saved_by_cluster_id(1234, root)
        self.assertIsNotNone(found)
        self.assertEqual(found.description, "Other v. Case")

    def test_slugless_directory_still_matches(self) -> None:
        from courtlistener_mcp.sources.courtlistener import find_saved_by_cluster_id

        root = Path(tempfile.mkdtemp())
        save_case(root, "cl-77", {"case_name": "No Slug", "citations": []})
        found = find_saved_by_cluster_id(77, root)
        self.assertIsNotNone(found)
        self.assertIsNone(find_saved_by_cluster_id(7, root))


class LegacyMetadataFallback(unittest.TestCase):
    """Libraries saved before metadata.json existed must keep working."""

    def test_yaml_only_case_still_resolves(self) -> None:
        root = Path(tempfile.mkdtemp())
        case_dir = save_legacy_case(
            root,
            "cl-42-legacy",
            {
                "case_name": "Legacy v. Old",
                "citations": ["384 U.S. 436", "86 S. Ct. 1602"],
                "lookup_citation": "384 U.S. 436",
                "source_url": "https://www.courtlistener.com/opinion/42/legacy/",
            },
        )

        metadata = read_metadata(case_dir)
        self.assertEqual(metadata["case_name"], "Legacy v. Old")
        self.assertEqual(
            _saved_citations(case_dir), {"384 u.s. 436", "86 s. ct. 1602"}
        )
        found = find_saved_by_citation("86 S. Ct. 1602", root)
        self.assertIsNotNone(found)
        self.assertEqual(found.description, "Legacy v. Old")
        self.assertIsNone(find_saved_by_citation("86 S. Ct. 16", root))

    def test_corrupt_json_falls_back_to_yaml(self) -> None:
        """A legacy case with a broken metadata.json still reads via its YAML."""
        root = Path(tempfile.mkdtemp())
        case_dir = save_legacy_case(
            root, "cl-43-corrupt", {"case_name": "Corrupt v. Json", "citations": ["1 A.2d 2"]}
        )
        (case_dir / "metadata.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(read_metadata(case_dir)["case_name"], "Corrupt v. Json")

    def test_corrupt_json_without_yaml_degrades_to_empty(self) -> None:
        """A connector-era case with corrupt JSON has no fallback: empty, not a crash."""
        root = Path(tempfile.mkdtemp())
        case_dir = save_case(root, "cl-44-corrupt", {"case_name": "X", "citations": []})
        (case_dir / "metadata.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(read_metadata(case_dir), {})


class SearchPagination(unittest.TestCase):
    """max_results must bound the walk, not truncate afterwards."""

    def test_stops_once_enough_results_collected(self) -> None:
        from courtlistener_mcp.sources import courtlistener as module

        pages_fetched = []

        class FakeResponse:
            def __init__(self, page: int) -> None:
                self.page = page

            def json(self) -> dict:
                return {
                    "results": [{"cluster_id": self.page * 10 + i} for i in range(20)],
                    "next": f"https://example.test/page{self.page + 1}",
                }

        def fake_get(url, **kwargs):
            page = len(pages_fetched) + 1
            pages_fetched.append(url)
            return FakeResponse(page)

        original_get, original_auth = module.get, module.auth_headers
        module.get = fake_get
        module.auth_headers = lambda: {}
        try:
            results = module.search_opinions({"q": "x"}, max_results=25)
        finally:
            module.get, module.auth_headers = original_get, original_auth

        self.assertEqual(len(results), 25)
        self.assertEqual(len(pages_fetched), 2, "should stop as soon as the cap is met")

    def test_page_limit_is_a_backstop(self) -> None:
        from courtlistener_mcp.sources import courtlistener as module

        calls = {"n": 0}

        class Endless:
            def json(self) -> dict:
                return {"results": [{"cluster_id": 1}], "next": "https://example.test/next"}

        def fake_get(url, **kwargs):
            calls["n"] += 1
            return Endless()

        original_get, original_auth = module.get, module.auth_headers
        module.get = fake_get
        module.auth_headers = lambda: {}
        try:
            module.search_opinions({"q": "x"}, max_pages=3)
        finally:
            module.get, module.auth_headers = original_get, original_auth

        self.assertEqual(calls["n"], 3, "an endless next chain must not loop forever")


class CourtLookups(unittest.TestCase):
    def test_known_court_resolves(self) -> None:
        self.assertEqual(get_court("ca9").court_id, "ca9")

    def test_lookup_is_case_insensitive(self) -> None:
        self.assertIsNotNone(get_court("CA9"))

    def test_unknown_court_is_none(self) -> None:
        self.assertIsNone(get_court("notacourt"))

    def test_require_court_raises_with_guidance(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            require_court("notacourt")
        self.assertIn("search_courts", str(ctx.exception))

    def test_state_abbreviation_is_a_single_court(self) -> None:
        """'ny' is the Court of Appeals only — the tools must not imply otherwise."""
        court = get_court("ny")
        self.assertIsNotNone(court)
        self.assertNotEqual(court.court_id, "nyappdiv")

    def test_search_requires_all_terms(self) -> None:
        results = search_courts("ninth circuit")
        self.assertTrue(results)
        self.assertTrue(any(c.court_id == "ca9" for c in results))


class FilenameSanitization(unittest.TestCase):
    def test_path_separators_are_removed(self) -> None:
        self.assertNotIn("/", sanitize_filename("a/b"))
        self.assertNotIn("\\", sanitize_filename("a\\b"))

    def test_traversal_segments_are_not_returned(self) -> None:
        """Slugs come from API responses and become directory names."""
        for hostile in ("..", ".", "../..", "./.."):
            with self.subTest(value=hostile):
                self.assertNotIn(
                    sanitize_filename(hostile), {".", ".."},
                    "sanitize_filename must never yield a traversal segment",
                )


class HttpTransport(unittest.TestCase):
    """Only the thin layer we own is tested here.

    Retry, backoff, Retry-After, gzip decoding and connection pooling belong to
    urllib3 and are not re-tested. What is ours is the Response shim, the error
    type, and the retry policy's configuration.
    """

    def test_retry_policy_covers_rate_limits_and_server_errors(self) -> None:
        self.assertIn(429, http.RETRY_STATUSES)
        for status in (500, 502, 503, 504):
            self.assertIn(status, http.RETRY_STATUSES)

    def test_retry_policy_honours_retry_after(self) -> None:
        self.assertTrue(http.RETRY_POLICY.respect_retry_after_header)

    def test_retry_policy_returns_final_response_instead_of_raising(self) -> None:
        """raise_on_status=False keeps the real status code visible to callers."""
        self.assertFalse(http.RETRY_POLICY.raise_on_status)

    def test_retry_policy_retries_posts_too(self) -> None:
        """Citation lookup is a POST and is safe to retry."""
        self.assertIn("POST", http.RETRY_POLICY.allowed_methods)

    def test_error_status_raises_httperror_with_code(self) -> None:
        response = http.Response(404, "https://example.test", b"nope")
        with self.assertRaises(http.HttpError) as ctx:
            response.raise_for_status()
        self.assertEqual(ctx.exception.status_code, 404)

    def test_success_status_does_not_raise(self) -> None:
        http.Response(200, "https://example.test", b"{}").raise_for_status()

    def test_json_parses_body(self) -> None:
        self.assertEqual(
            http.Response(200, "https://example.test", b'{"ok": true}').json(), {"ok": True}
        )

    def test_empty_body_json_is_an_httperror_not_a_crash(self) -> None:
        with self.assertRaises(http.HttpError):
            http.Response(200, "https://example.test", b"").json()

    def test_malformed_json_is_an_httperror(self) -> None:
        with self.assertRaises(http.HttpError):
            http.Response(200, "https://example.test", b"{nope").json()

    def test_undecodable_bytes_do_not_crash_text(self) -> None:
        self.assertIn("\ufffd", http.Response(200, "u", b"\xff\xfe bad").text)

    def test_transport_failure_becomes_httperror(self) -> None:
        class Boom:
            def request(self, *a, **k):
                raise http.urllib3.exceptions.NewConnectionError(None, "refused")

        original = http._POOL
        http._POOL = Boom()
        try:
            with self.assertRaises(http.HttpError) as ctx:
                http.get("https://example.test/x", timeout=1)
        finally:
            http._POOL = original
        self.assertIn("Could not reach", str(ctx.exception))


class DependencyProbe(unittest.TestCase):
    """The startup probe must name every module the server actually imports.

    Regression: when `requests` was replaced by `urllib3`, the probe still only
    checked `bs4`, so check_setup reported "Dependencies: OK" while the first
    network call was about to raise ModuleNotFoundError.
    """

    def _server_module(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "cl_server", MCP_DIR / "server.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _third_party_imports(tree, stdlib: set[str]) -> tuple[set[str], set[str]]:
        """Split third-party imports into (required, optional).

        An import guarded by ``try/except ImportError`` is optional by
        construction — the code has a documented fallback — so it must not be
        promoted into REQUIRED_MODULES, which would make it fatal.
        """
        import ast

        optional_nodes: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                handles_import_error = any(
                    (isinstance(h.type, ast.Name) and h.type.id == "ImportError")
                    or (
                        isinstance(h.type, ast.Tuple)
                        and any(
                            isinstance(e, ast.Name) and e.id == "ImportError"
                            for e in h.type.elts
                        )
                    )
                    or h.type is None
                    for h in node.handlers
                )
                if handles_import_error:
                    for child in ast.walk(node):
                        optional_nodes.add(id(child))

        required: set[str] = set()
        optional: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]] if node.level == 0 else []
            else:
                continue
            for name in names:
                if not name or name in stdlib or name == "courtlistener_mcp":
                    continue
                (optional if id(node) in optional_nodes else required).add(name)
        return required, optional

    def test_probe_covers_every_required_third_party_import(self) -> None:
        """Every unguarded third-party import must appear in REQUIRED_MODULES."""
        import ast

        declared = set(self._server_module().REQUIRED_MODULES)
        stdlib = set(sys.stdlib_module_names)
        required: set[str] = set()
        for path in (MCP_DIR / "lib" / "courtlistener_mcp").rglob("*.py"):
            found, _ = self._third_party_imports(
                ast.parse(path.read_text(encoding="utf-8")), stdlib
            )
            required |= found

        unprobed = required - declared
        self.assertFalse(
            unprobed,
            f"third-party imports not covered by REQUIRED_MODULES: {sorted(unprobed)}",
        )

    def test_optional_imports_are_not_required(self) -> None:
        """certifi is a guarded import with a fallback; it must stay optional."""
        import ast

        declared = set(self._server_module().REQUIRED_MODULES)
        stdlib = set(sys.stdlib_module_names)
        optional: set[str] = set()
        for path in (MCP_DIR / "lib" / "courtlistener_mcp").rglob("*.py"):
            _, found = self._third_party_imports(
                ast.parse(path.read_text(encoding="utf-8")), stdlib
            )
            optional |= found

        self.assertIn("certifi", optional, "certifi should be a guarded import")
        self.assertFalse(
            optional & declared,
            "an optional import must not be listed as required",
        )

    def test_declared_modules_are_importable_here(self) -> None:
        import importlib as il

        for name in self._server_module().REQUIRED_MODULES:
            with self.subTest(module=name):
                il.import_module(name)


class RecapCacheSemantics(unittest.TestCase):
    """refresh must bypass the cache read but still update the cache."""

    def _run(
        self,
        use_cache: bool,
        cached: dict | None,
        fresh: dict,
        cache_age_seconds: float = 0.0,
    ) -> tuple[dict, dict | None, int]:
        import json as jsonlib
        import tempfile
        from pathlib import Path as P

        from courtlistener_mcp.sources import recap

        cache_dir = P(tempfile.mkdtemp())
        url = "https://example.test/api"
        key = recap._cache_key(url, None)
        if cached is not None:
            cached_path = cache_dir / f"{key}.json"
            cached_path.write_text(jsonlib.dumps(cached), encoding="utf-8")
            if cache_age_seconds:
                import os, time as time_mod

                past = time_mod.time() - cache_age_seconds
                os.utime(cached_path, (past, past))

        calls = {"n": 0}

        class FakeResponse:
            status_code = 200

            def __init__(self, u: str):
                self.url = u

            def json(self):
                return fresh

        def fake_get(u, **kw):
            calls["n"] += 1
            return FakeResponse(u)

        original_get, original_auth = recap.get, recap.auth_headers
        recap.get, recap.auth_headers = fake_get, lambda: {}
        try:
            result = recap._cached_json_get(url, cache_dir=cache_dir, use_cache=use_cache)
        finally:
            recap.get, recap.auth_headers = original_get, original_auth

        on_disk_path = cache_dir / f"{key}.json"
        on_disk = jsonlib.loads(on_disk_path.read_text()) if on_disk_path.exists() else None
        return result, on_disk, calls["n"]

    def test_cached_read_skips_network(self) -> None:
        result, _, network_calls = self._run(True, {"v": "old"}, {"v": "new"})
        self.assertEqual(result, {"v": "old"})
        self.assertEqual(network_calls, 0)

    def test_refresh_fetches_fresh_and_updates_cache(self) -> None:
        result, on_disk, network_calls = self._run(False, {"v": "old"}, {"v": "new"})
        self.assertEqual(result, {"v": "new"})
        self.assertEqual(network_calls, 1)
        self.assertEqual(on_disk, {"v": "new"}, "refresh must write back, not discard")

    def test_first_fetch_populates_cache(self) -> None:
        result, on_disk, _ = self._run(True, None, {"v": "new"})
        self.assertEqual(result, {"v": "new"})
        self.assertEqual(on_disk, {"v": "new"})

    def test_fresh_entry_within_ttl_is_served(self) -> None:
        from courtlistener_mcp.sources import recap

        result, _, network_calls = self._run(
            True, {"v": "old"}, {"v": "new"},
            cache_age_seconds=recap.DEFAULT_CACHE_TTL_SECONDS / 2,
        )
        self.assertEqual(result, {"v": "old"})
        self.assertEqual(network_calls, 0)

    def test_sweep_deletes_expired_and_keeps_fresh(self) -> None:
        import os
        import tempfile
        import time as time_mod
        from pathlib import Path as P

        from courtlistener_mcp.sources import recap

        cache_dir = P(tempfile.mkdtemp())
        old = cache_dir / "aaaa.json"
        old.write_text("{}", encoding="utf-8")
        past = time_mod.time() - recap.DEFAULT_CACHE_TTL_SECONDS - 3600
        os.utime(old, (past, past))
        fresh = cache_dir / "bbbb.json"
        fresh.write_text("{}", encoding="utf-8")

        recap._SWEPT_DIRS.discard(cache_dir)
        recap._sweep_expired(cache_dir)
        self.assertFalse(old.exists(), "expired file must be deleted")
        self.assertTrue(fresh.exists(), "fresh file must survive the sweep")

    def test_sweep_runs_once_per_directory(self) -> None:
        import os
        import tempfile
        import time as time_mod
        from pathlib import Path as P

        from courtlistener_mcp.sources import recap

        cache_dir = P(tempfile.mkdtemp())
        recap._SWEPT_DIRS.discard(cache_dir)
        recap._sweep_expired(cache_dir)

        late = cache_dir / "cccc.json"
        late.write_text("{}", encoding="utf-8")
        past = time_mod.time() - recap.DEFAULT_CACHE_TTL_SECONDS - 3600
        os.utime(late, (past, past))
        recap._sweep_expired(cache_dir)  # second call: already swept, no-op
        self.assertTrue(late.exists(), "sweep must not repeat within one process")

    def test_expired_entry_is_refetched_and_rewritten(self) -> None:
        """A docket cached yesterday must not hide today's filings forever."""
        from courtlistener_mcp.sources import recap

        result, on_disk, network_calls = self._run(
            True, {"v": "old"}, {"v": "new"},
            cache_age_seconds=recap.DEFAULT_CACHE_TTL_SECONDS + 3600,
        )
        self.assertEqual(result, {"v": "new"})
        self.assertEqual(network_calls, 1)
        self.assertEqual(on_disk, {"v": "new"}, "expiry must refresh the cache in place")


class BatchGetOpinion(unittest.TestCase):
    """Batch retrieval: per-item isolation, dedup, and the per-call cap."""

    def _server(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("cl_server_b", MCP_DIR / "server.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_jobs_dedup_and_skip_blank(self) -> None:
        server = self._server()
        jobs = server._gather_opinion_jobs(
            {
                "citations": ["1 U.S. 1", "2 U.S. 2", "1 U.S. 1", "  "],
                "urls": ["https://www.courtlistener.com/opinion/9/x/"],
            }
        )
        self.assertEqual(
            jobs,
            [
                ("citation", "1 U.S. 1"),
                ("citation", "2 U.S. 2"),
                ("url", "https://www.courtlistener.com/opinion/9/x/"),
            ],
        )

    def test_singular_forms_are_rejected(self) -> None:
        """Pre-release cleanup: there is no singular citation/url argument."""
        server = self._server()
        with self.assertRaises(ValueError):
            server.tool_get_opinions({"citation": "1 U.S. 1"})

    def test_empty_args_rejected(self) -> None:
        server = self._server()
        with self.assertRaises(ValueError):
            server.tool_get_opinions({})

    def test_cap_enforced_with_guidance(self) -> None:
        server = self._server()
        many = {"citations": [f"{i} U.S. {i}" for i in range(1, 60)]}
        with self.assertRaises(ValueError) as ctx:
            server.tool_get_opinions(many)
        self.assertIn("download_search_results", str(ctx.exception))

    def test_one_failure_does_not_abort_the_batch(self) -> None:
        import json as jsonlib

        from courtlistener_mcp.models import SavedSource
        from courtlistener_mcp.sources import courtlistener as sources

        server = self._server()

        def fake_fetch(citation, *, output_dir=None, refresh=False):
            if "404" in citation:
                raise sources.CitationNotFoundError(f"no such case: {citation}")
            return SavedSource(
                source_family="courtlistener",
                path=Path("/tmp/cl-1-case"),
                source_url="https://www.courtlistener.com/opinion/1/case/",
                description=f"Case for {citation}",
                status="downloaded",
            )

        original = sources.fetch_by_citation
        sources.fetch_by_citation = fake_fetch
        try:
            output = server.tool_get_opinions(
                {"citations": ["1 U.S. 1", "404 U.S. 404", "2 U.S. 2"]}
            )
        finally:
            sources.fetch_by_citation = original

        payload = jsonlib.loads(output)
        statuses = [r["status"] for r in payload["results"]]
        self.assertEqual(statuses, ["downloaded", "not_found", "downloaded"])
        self.assertEqual(payload["summary"], {"downloaded": 2, "not_found": 1})


class PdfDownloadCap(unittest.TestCase):
    """The cap bounds NEW downloads, reports the remainder loudly, and resumes."""

    def _run(self, tmp_root: Path, n_docs: int, existing: int = 0, max_pdfs: int | None = None):
        import importlib.util
        import json as jsonlib

        spec = importlib.util.spec_from_file_location("cl_server_p", MCP_DIR / "server.py")
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)

        from courtlistener_mcp.sources import recap

        docs = [
            recap.RecapDocumentRef(
                docket_id=1, docket_entry_id=i, entry_number=i, entry_date="2026-01-01",
                entry_description=f"Entry {i}", document_id=100 + i, document_number=str(i),
                attachment_number=None, description=f"Doc {i}", pacer_doc_id=str(i),
                is_available=True, filepath_local=f"recap/doc{i}.pdf", page_count=1,
            )
            for i in range(1, n_docs + 1)
        ]
        docket = {"id": 1, "case_name": "Cap v. Test", "court_id": "nysd",
                  "docket_number": "1:26-cv-1", "slug": "cap-v-test"}

        downloads = {"n": 0}

        def fake_download(doc, pdf_dir, *, overwrite=False):
            path = pdf_dir / recap.pdf_filename(doc)
            if path.exists() and not overwrite:
                return path
            downloads["n"] += 1
            path.write_bytes(b"pdf")
            return path

        # Pre-seed already-saved files.
        out_dir = recap.docket_output_dir(docket, data_dir=tmp_root)
        pdf_dir = out_dir / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        for doc in docs[:existing]:
            (pdf_dir / recap.pdf_filename(doc)).write_bytes(b"pdf")

        import os
        os.environ["COURTLISTENER_DATA_DIR"] = str(tmp_root)
        server._resolve_docket = lambda args, cache_dir, use_cache=True: docket
        server._collect_documents = lambda docket_id, args, cache_dir, use_cache=True: ([], docs)
        recap.download_document = fake_download

        args = {"docket_id": 1, "entry_numbers": [1]}
        if max_pdfs is not None:
            args["max_pdfs"] = max_pdfs
        try:
            return server.tool_download_docket_pdfs(args), downloads["n"]
        finally:
            os.environ.pop("COURTLISTENER_DATA_DIR", None)

    def test_cap_stops_new_downloads_and_reports_remainder(self) -> None:
        out, downloaded = self._run(Path(tempfile.mkdtemp()), n_docs=8, max_pdfs=5)
        self.assertEqual(downloaded, 5)
        self.assertIn("STOPPED AT THE 5-PDF LIMIT", out)
        self.assertIn("3 available PDF(s) were NOT downloaded", out)
        self.assertIn("Newly downloaded: 5", out)

    def test_under_cap_reports_no_truncation(self) -> None:
        out, downloaded = self._run(Path(tempfile.mkdtemp()), n_docs=3, max_pdfs=5)
        self.assertEqual(downloaded, 3)
        self.assertNotIn("STOPPED", out)

    def test_repeat_call_resumes_past_existing_files(self) -> None:
        """Existing files must not consume the cap, so a second call finishes."""
        root = Path(tempfile.mkdtemp())
        _, first = self._run(root, n_docs=8, max_pdfs=5)
        out, second = self._run(root, n_docs=8, existing=0, max_pdfs=5)
        self.assertEqual(first, 5)
        self.assertEqual(second, 3, "second call should download only the remainder")
        self.assertNotIn("STOPPED", out)
        self.assertIn("Already saved: 5", out)


class VerifyCitations(unittest.TestCase):
    """One POST verifies a whole document; verdicts map API statuses honestly."""

    def _run(self, api_items):
        from courtlistener_mcp.sources import courtlistener as sources

        class FakeResponse:
            def json(self):
                return api_items

        original = sources.post
        sources.post = lambda *a, **k: FakeResponse()
        sources_auth = sources.auth_headers
        sources.auth_headers = lambda: {}
        try:
            return sources.verify_citations_in_text("some brief text")
        finally:
            sources.post = original
            sources.auth_headers = sources_auth

    def test_status_mapping(self) -> None:
        results = self._run([
            {"citation": "1 U.S. 1", "status": 200, "normalized_citations": ["1 U.S. 1"],
             "clusters": [{"case_name": "Real v. Case", "absolute_url": "/opinion/1/x/", "date_filed": "1800-01-01"}]},
            {"citation": "9 Fake 99", "status": 404, "normalized_citations": [], "clusters": []},
            {"citation": "5 F.3d 1", "status": 300, "normalized_citations": ["5 F.3d 1"],
             "clusters": [{"case_name": "A"}, {"case_name": "B"}]},
        ])
        self.assertEqual([r["verdict"] for r in results], ["found", "not_found", "ambiguous"])
        self.assertIn("courtlistener.com", results[0]["matches"][0]["url"])

    def test_found_without_clusters_is_not_found(self) -> None:
        results = self._run([{"citation": "x", "status": 200, "clusters": []}])
        self.assertEqual(results[0]["verdict"], "not_found")

    def test_oversized_text_rejected_with_guidance(self) -> None:
        from courtlistener_mcp.sources import courtlistener as sources

        with self.assertRaises(ValueError) as ctx:
            sources.verify_citations_in_text("x" * 60_000)
        self.assertIn("Split the document", str(ctx.exception))


class CitingOpinions(unittest.TestCase):
    """Later-treatment search must cover every opinion record in a cluster.

    Regression for the undercount trap: Jerman v. Carlisle's lead opinion alone
    matches 48 citing opinions, the whole cluster 175. Searching one id looks
    like a working citator while silently hiding most of the treatment.
    """

    def test_all_sibling_opinions_collected(self) -> None:
        from courtlistener_mcp.sources.courtlistener import sibling_opinion_ids

        cluster = {
            "sub_opinions": [
                "https://www.courtlistener.com/api/rest/v4/opinions/2357/",
                "https://www.courtlistener.com/api/rest/v4/opinions/9413270/",
                "https://www.courtlistener.com/api/rest/v4/opinions/9413273/",
            ]
        }
        self.assertEqual(sibling_opinion_ids(cluster), [2357, 9413270, 9413273])

    def test_missing_or_malformed_sub_opinions(self) -> None:
        from courtlistener_mcp.sources.courtlistener import sibling_opinion_ids

        self.assertEqual(sibling_opinion_ids({}), [])
        self.assertEqual(sibling_opinion_ids({"sub_opinions": None}), [])
        # A non-numeric tail must be skipped, not crash or become a bogus id.
        self.assertEqual(
            sibling_opinion_ids({"sub_opinions": ["/opinions/abc/", "/opinions/7/"]}),
            [7],
        )

    def test_query_unions_every_sibling(self) -> None:
        from courtlistener_mcp.sources.courtlistener import build_cites_query

        self.assertEqual(
            build_cites_query([2357, 9413270]), "cites:(2357 OR 9413270)"
        )

    def test_query_text_filter_is_anded(self) -> None:
        from courtlistener_mcp.sources.courtlistener import build_cites_query

        self.assertEqual(
            build_cites_query([7], '"declined to follow"'),
            'cites:(7) AND ("declined to follow")',
        )
        # Whitespace-only text must not produce a dangling AND ().
        self.assertEqual(build_cites_query([7], "   "), "cites:(7)")

    def test_empty_ids_rejected(self) -> None:
        from courtlistener_mcp.sources.courtlistener import build_cites_query

        with self.assertRaises(ValueError):
            build_cites_query([])


if __name__ == "__main__":
    unittest.main(verbosity=2)
