#!/usr/bin/env python3
"""Drive the CourtListener MCP server over stdio and report pass/fail per check.

Offline checks run with no configuration. Network checks run only when an API
key is available, so the script is useful before and after setup.

Usage:
    python3 tools/courtlistener/smoke_test.py
    COURTLISTENER_API_KEY=... python3 tools/courtlistener/smoke_test.py
    python3 tools/courtlistener/smoke_test.py --server dist/courtlistener/server/server.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SERVER = REPO_ROOT / "plugins" / "courtlistener" / "mcp" / "server.py"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


class Session:
    """A single stdio JSON-RPC conversation with the server."""

    def __init__(self, server_path: Path, env: dict[str, str]):
        self.process = subprocess.Popen(
            [sys.executable, str(server_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
        )
        self.next_id = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        request = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            request["params"] = params
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"server closed the stream. stderr:\n{stderr}")
        return json.loads(line)

    def tool(self, name: str, arguments: dict | None = None) -> tuple[str, bool]:
        response = self.call("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in response:
            return response["error"]["message"], True
        result = response["result"]
        return result["content"][0]["text"], bool(result.get("isError", False))

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def ok(self, label: str, detail: str = "") -> None:
        self.passed += 1
        print(f"  {GREEN}PASS{RESET}  {label}" + (f"  {DIM}{detail}{RESET}" if detail else ""))

    def fail(self, label: str, detail: str = "") -> None:
        self.failed += 1
        print(f"  {RED}FAIL{RESET}  {label}" + (f"  {DIM}{detail}{RESET}" if detail else ""))

    def skip(self, label: str, why: str) -> None:
        self.skipped += 1
        print(f"  {YELLOW}SKIP{RESET}  {label}  {DIM}{why}{RESET}")

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        (self.ok if condition else self.fail)(label, detail)


def first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else "(empty)"


def run(server_path: Path, library_dir: Path | None, api_key: str | None) -> int:
    env = dict(os.environ)
    env.pop("COURTLISTENER_API_KEY", None)
    env.pop("COURTLISTENER_DATA_DIR", None)
    if api_key:
        env["COURTLISTENER_API_KEY"] = api_key
    if library_dir:
        env["COURTLISTENER_DATA_DIR"] = str(library_dir)

    report = Report()
    print(f"\nServer:  {server_path}")
    print(f"Library: {library_dir or '(not configured)'}")
    print(f"API key: {'provided' if api_key else 'absent — network checks will be skipped'}\n")

    print("Protocol")
    session = Session(server_path, env)
    try:
        response = session.call(
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {},
             "clientInfo": {"name": "smoke-test", "version": "1"}},
        )
        result = response.get("result", {})
        report.check(
            "initialize returns a protocol version and serverInfo",
            "protocolVersion" in result and "serverInfo" in result,
            result.get("protocolVersion", ""),
        )

        response = session.call("tools/list")
        tools = response.get("result", {}).get("tools", [])
        names = [tool["name"] for tool in tools]
        report.check("tools/list returns 12 tools", len(tools) == 12, f"{len(tools)} found")
        report.check(
            "every tool declares an inputSchema",
            all("inputSchema" in tool for tool in tools),
        )

        response = session.call("ping")
        report.check("ping responds", "result" in response)

        print("\nOffline tools")
        text, is_error = session.tool("read_search_docs")
        report.check(
            "read_search_docs returns the bundled query guide",
            not is_error and "Intersections: AND or &" in text and "Fielded Queries" in text,
            first_line(text),
        )

        text, is_error = session.tool("search_courts", {"query": "ninth circuit"})
        report.check("search_courts finds ca9", not is_error and "ca9" in text, first_line(text))

        text, is_error = session.tool("check_court_ids", {"court_ids": ["nyappdiv"]})
        report.check(
            "check_court_ids resolves nyappdiv",
            not is_error and "Appellate Division" in text,
            first_line(text),
        )

        text, is_error = session.tool(
            "check_court_ids", {"court_ids": ["nysd", "notacourt"]}
        )
        report.check(
            "check_court_ids flags a bad ID without failing the batch",
            "UNKNOWN" in text and "S.D. New York" in text,
            first_line(text),
        )

        print("\nError handling")
        response = session.call("tools/call", {"name": "does_not_exist", "arguments": {}})
        report.check("unknown tool returns a JSON-RPC error", "error" in response)

        text, is_error = session.tool("search_courts", {})
        report.check("missing required argument is reported", is_error, first_line(text))

        print("\nSetup check")
        text, is_error = session.tool("check_setup")
        report.check("check_setup runs", not is_error)
        report.check("dependencies resolve", "Dependencies: OK" in text,
                     "runtime deps import cleanly")
        if api_key:
            report.check("API key is seen by the server", "API key: found" in text)
            report.check(
                "CourtListener connection succeeds",
                "CourtListener connection: OK" in text,
                first_line(text.split("connection:")[-1]) if "connection:" in text else "",
            )
        else:
            report.skip("API key recognised", "no key provided")
            report.skip("CourtListener connection", "no key provided")

        print("\nNetwork tools")
        if not api_key:
            for label in ("search_opinions", "get_opinions", "search_recap"):
                report.skip(label, "no key provided")
        else:
            text, is_error = session.tool(
                "search_opinions", {"query": 'caseName:"Miranda"', "limit": 3}
            )
            report.check("search_opinions returns results", not is_error and "Found" in text,
                         first_line(text))

            text, is_error = session.tool(
                "get_opinions", {"citations": ["384 U.S. 436"]}
            )
            saved_ok = False
            item = {}
            if not is_error:
                try:
                    payload = json.loads(text)
                    item = (payload.get("results") or [{}])[0]
                    saved_ok = item.get("status") in {"downloaded", "already_saved"}
                    detail = (
                        f"{item.get('case_name', '?')} -> "
                        f"{payload.get('library_root', '?')}/{item.get('opinion_path', '?')}"
                    )
                except json.JSONDecodeError:
                    detail = first_line(text)
            else:
                detail = first_line(text)
            report.check("get_opinions retrieves Miranda v. Arizona", saved_ok, detail)

            if saved_ok and library_dir:
                opinion_path = Path(payload["library_root"]) / item["opinion_path"]
                case_dir = opinion_path.parent
                report.check(
                    "opinion files landed on disk",
                    opinion_path.exists()
                    and all((case_dir / n).exists()
                            for n in ("opinion.html", "metadata.json")),
                    str(case_dir),
                )
            else:
                report.skip("opinion files on disk", "retrieval did not succeed")

            text, is_error = session.tool(
                "search_recap", {"query": 'party:("Microsoft Corporation")', "limit": 3}
            )
            report.check("search_recap returns results", not is_error, first_line(text))
    finally:
        session.close()

    print(f"\n{report.passed} passed, {report.failed} failed, {report.skipped} skipped\n")
    return 1 if report.failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=str(DEFAULT_SERVER), help="Path to server.py")
    parser.add_argument(
        "--library",
        default=os.getenv("COURTLISTENER_DATA_DIR"),
        help="Library folder to use for the run (default: $COURTLISTENER_DATA_DIR)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("COURTLISTENER_API_KEY"),
        help="CourtListener API key (default: $COURTLISTENER_API_KEY)",
    )
    args = parser.parse_args()

    library = Path(args.library).expanduser().resolve() if args.library else None
    raise SystemExit(run(Path(args.server).resolve(), library, args.api_key))


if __name__ == "__main__":
    main()
