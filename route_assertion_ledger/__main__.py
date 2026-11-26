import argparse
import json
import os
import stat
import sys
from pathlib import Path
from . import (InvalidInput, MAX_SPEC_BYTES, MAX_EVIDENCE_BYTES, MAX_POLICY_BYTES,
               audit, load_json, load_observations_jsonl)
from .report import html_report


def _file_identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_input(path, limit, *, jsonl=False):
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise InvalidInput("regular bounded input files required")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as f:
        opened = os.fstat(f.fileno())
        if not stat.S_ISREG(opened.st_mode) or _file_identity(opened) != _file_identity(before):
            raise InvalidInput("input changed during read")
        raw = f.read(opened.st_size + 1)
        final = os.fstat(f.fileno())
        named = path.lstat()
        if (len(raw) != opened.st_size or _file_identity(final) != _file_identity(opened)
                or not stat.S_ISREG(named.st_mode) or _file_identity(named) != _file_identity(opened)):
            raise InvalidInput("input changed during read")
        return load_observations_jsonl(raw) if jsonl else load_json(raw, limit)


def _write_report(result):
    # Bounded result; avoid an unhandled buffered stdout exception at shutdown.
    data = json.dumps(result, ensure_ascii=True, sort_keys=True).encode("ascii") + bytes((10,))
    view = memoryview(data)
    while view:
        count = os.write(sys.stdout.fileno(), view)
        if count <= 0:
            raise OSError("output unavailable")
        view = view[count:]


def _error(message):
    try:
        _write_report({"ok": False, "error": message})
    except OSError:
        pass
    return 2



def preflight_main(argv):
    from .preflight import preflight, MAX_DOCUMENTS, MAX_TOTAL_BYTES
    p = argparse.ArgumentParser(description="Inventory local spec references and duplicate operation IDs without resolving anything")
    p.add_argument("specs", nargs="+", help="1–8 OpenAPI 3.0/3.1 or Swagger 2.0 JSON files")
    args = p.parse_args(argv)
    try:
        if not 1 <= len(args.specs) <= MAX_DOCUMENTS:
            raise InvalidInput("choose 1 to 8 local spec documents")
        # Reserve the full per-document cap before opening each file. This
        # keeps the worst-case aggregate bounded even if sizes change.
        if len(args.specs) * MAX_SPEC_BYTES > MAX_TOTAL_BYTES:
            raise InvalidInput("aggregate preflight file budget exceeded")
        specs = [read_input(path, MAX_SPEC_BYTES) for path in args.specs]
        result = preflight(specs)
        _write_report(result)
        return 0 if result["ok"] else 1
    except InvalidInput as exc:
        return _error(str(exc))
    except (OSError, RecursionError, TypeError, ValueError):
        return _error("input or output unavailable")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--preflight":
        return preflight_main(argv[1:])
    if argv == ['--gui']:
        from .desktop import main as gui_main
        return gui_main()
    p = argparse.ArgumentParser(description="Audit normalized API test assertion coverage (offline)", epilog="Use --gui by itself for the local desktop, or --preflight SPEC [MORE_SPECS ...] for spec inventory.")
    p.add_argument("spec", help="OpenAPI 3.0 or 3.1 JSON file")
    p.add_argument("observations", help="JSON array of operation/status/asserted records")
    p.add_argument("--observations-format", choices=("json", "jsonl"), default="json",
                   help="Normalized observation array (default) or one JSON record per line")
    p.add_argument("--policy", help="Optional exclusions and required response statuses")
    p.add_argument("--expected-scope-sha256", help="Require a separately reviewed lowercase SHA-256 scope fingerprint")
    p.add_argument("--html", help="Write a new script-free HTML report; never overwrite existing files")
    args = p.parse_args(argv)
    try:
        spec = read_input(args.spec, MAX_SPEC_BYTES)
        observations = read_input(args.observations, MAX_EVIDENCE_BYTES,
                                  jsonl=args.observations_format == "jsonl")
        policy = read_input(args.policy, MAX_POLICY_BYTES) if args.policy else None
        if args.policy and policy is None:
            raise InvalidInput("policy must be a JSON object")
        result = audit(spec, observations, policy, expected_scope_sha256=args.expected_scope_sha256)
        if args.html:
            fd = os.open(args.html, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_BINARY", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(html_report(result))
        _write_report(result)
        return 0 if result["ok"] else 1
    except InvalidInput as exc:
        return _error(str(exc))
    except (OSError, RecursionError, TypeError, ValueError):
        return _error("input or output unavailable")


if __name__ == "__main__":
    raise SystemExit(main())
