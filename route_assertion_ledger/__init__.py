"""Offline operation/response assertion coverage over explicitly normalized records."""
import hashlib
import json
import math
import re

MAX_SPEC_BYTES = 512 * 1024
MAX_EVIDENCE_BYTES = 1024 * 1024
MAX_POLICY_BYTES = 256 * 1024
MAX_OPERATIONS = 1000
MAX_RESPONSES = 5000
MAX_OBSERVATIONS = 5000
METHODS = frozenset("GET PUT POST DELETE OPTIONS HEAD PATCH TRACE".split())
_LITERAL = re.compile(r"[A-Za-z0-9._~!$&'()+,;=:@-]+", re.ASCII)
_PARAMETER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_.-]{0,63}\}", re.ASCII)
_RESPONSE = re.compile(r"(?:[1-5][0-9]{2}|[1-5]XX|default)", re.ASCII)
_VERSION = re.compile(r"3\.[01]\.[0-9]{1,4}", re.ASCII)


class InvalidInput(ValueError):
    """An unsupported or malformed input; messages never contain input values."""


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInput("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_):
    raise InvalidInput("non-standard JSON numeric constant")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise InvalidInput("non-finite JSON number")
    return number


def _bounded_structure(text):
    """Check depth before calling the recursive JSON parser, ignoring quoted text."""
    depth = 0
    containers = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            containers += 1
            if depth > 64 or containers > 50000:
                raise InvalidInput("JSON structure exceeds depth or container limit")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise InvalidInput("invalid JSON structure")


def load_json(raw, limit):
    if not isinstance(raw, bytes) or len(raw) > limit:
        raise InvalidInput("input exceeds byte limit")
    try:
        text = raw.decode("utf-8-sig")
        _bounded_structure(text)
        return json.loads(text, object_pairs_hook=_reject_duplicates,
                          parse_constant=_reject_constant, parse_float=_finite_float)
    except InvalidInput:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise InvalidInput("invalid or excessively nested UTF-8 JSON") from None


def load_observations_jsonl(raw):
    """Bounded newline-delimited normalized records; blank lines are invalid."""
    if not isinstance(raw, bytes) or len(raw) > MAX_EVIDENCE_BYTES:
        raise InvalidInput("observations exceed byte limit")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if not raw:
        return []
    lines = raw.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    if len(lines) > MAX_OBSERVATIONS:
        raise InvalidInput("too many observation records")
    result = []
    for line in lines:
        if not line.strip() or len(line) > 8192:
            raise InvalidInput("blank or oversized JSONL observation")
        result.append(load_json(line, 8192))
    return result


def _route_shape(path):
    if not isinstance(path, str) or len(path) > 256 or not path.startswith("/"):
        raise InvalidInput("invalid or oversized declared route")
    if path == "/":
        return ()
    # Deliberately support only literal or complete template segments.
    parts = path[1:].split("/")
    if len(parts) > 32:
        raise InvalidInput("route has too many segments")
    shape = []
    names = set()
    for part in parts:
        if _PARAMETER.fullmatch(part):
            if part in names:
                raise InvalidInput("repeated path parameter")
            names.add(part)
            shape.append("{}")
        elif _LITERAL.fullmatch(part) and part not in (".", ".."):
            shape.append(part)
        else:
            raise InvalidInput("unsupported declared path segment")
    return tuple(shape)


def _operations(spec):
    if not isinstance(spec, dict) or not isinstance(spec.get("openapi"), str) or not _VERSION.fullmatch(spec["openapi"]):
        raise InvalidInput("only OpenAPI 3.0 and 3.1 JSON documents are supported")
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise InvalidInput("nonempty paths object required")
    if len(paths) > MAX_OPERATIONS:
        raise InvalidInput("too many declared paths")
    operations, shapes = {}, set()
    total_responses = 0
    for path, item in paths.items():
        if not isinstance(path, str):
            raise InvalidInput("invalid declared path key")
        if path.startswith("x-"):
            continue
        shape = _route_shape(path)
        if shape in shapes:
            raise InvalidInput("duplicate path template shape")
        shapes.add(shape)
        if not isinstance(item, dict) or "$ref" in item:
            raise InvalidInput("path-item references are not supported")
        for key, op in item.items():
            if not isinstance(key, str):
                raise InvalidInput("invalid path item field")
            if key in ("summary", "description", "servers", "parameters") or key.startswith("x-"):
                continue
            method = key.upper()
            if key != method.lower() or method not in METHODS or not isinstance(op, dict):
                raise InvalidInput("unsupported path item field")
            responses = op.get("responses")
            if not isinstance(responses, dict) or not responses:
                raise InvalidInput("each operation must declare responses")
            codes = set()
            for code, response in responses.items():
                if not isinstance(code, str):
                    raise InvalidInput("invalid response status key")
                if code.startswith("x-"):
                    continue
                if not _RESPONSE.fullmatch(code) or not isinstance(response, dict):
                    raise InvalidInput("invalid declared response")
                codes.add(code)
                total_responses += 1
                if total_responses > MAX_RESPONSES:
                    raise InvalidInput("too many declared responses")
            if not codes:
                raise InvalidInput("operation has no declared status codes")
            operations[f"{method} {path}"] = codes
            if len(operations) > MAX_OPERATIONS:
                raise InvalidInput("too many declared operations")
    if not operations:
        raise InvalidInput("no supported HTTP operations")
    return operations


def _status_valid(code):
    return type(code) is int and 100 <= code <= 599


def _declared(codes, status):
    return str(status) in codes or f"{status // 100}XX" in codes or "default" in codes


def _policy(policy, operations):
    if policy is None:
        policy = {}
    if not isinstance(policy, dict) or set(policy) - {"exclude", "required_statuses", "assert_all_observed"}:
        raise InvalidInput("invalid policy fields")
    exclude = policy.get("exclude", {})
    required = policy.get("required_statuses", {})
    strict = policy.get("assert_all_observed", False)
    if type(strict) is not bool:
        raise InvalidInput("assert_all_observed must be boolean")
    if not isinstance(exclude, dict) or not isinstance(required, dict):
        raise InvalidInput("invalid policy object")
    if len(exclude) > MAX_OPERATIONS or len(required) > MAX_OPERATIONS:
        raise InvalidInput("oversized policy")
    for op, reason in exclude.items():
        if op not in operations or not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
            raise InvalidInput("excluded operation requires a known route and reason")
    for op, statuses in required.items():
        if op not in operations or op in exclude or not isinstance(statuses, list) or not 1 <= len(statuses) <= 20:
            raise InvalidInput("invalid required-status rule")
        if not all(_status_valid(v) and _declared(operations[op], v) for v in statuses):
            raise InvalidInput("required status must be declared by the operation")
        if len(set(statuses)) != len(statuses):
            raise InvalidInput("duplicate required status")
    if len(exclude) == len(operations):
        raise InvalidInput("policy cannot exclude every operation")
    # Exclusion reasons are deliberately not included in the output.
    return set(exclude), {op: set(codes) for op, codes in required.items()}, strict


def audit(spec, observations, policy=None, *, expected_scope_sha256=None):
    """Return a deterministic, privacy-minimized report. No observed paths/values are echoed.

    Observations must be trusted test-runner statements containing an exact declared
    operation key, numeric response status and an explicit boolean assertion flag.
    This tool does not prove that a request was executed or an assertion was correct.
    """
    if expected_scope_sha256 is not None and (not isinstance(expected_scope_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_scope_sha256, re.ASCII)):
        raise InvalidInput("expected scope fingerprint must be lowercase SHA-256 hex")
    operations = _operations(spec)
    exclude, required, strict = _policy(policy, operations)
    if not isinstance(observations, list) or len(observations) > MAX_OBSERVATIONS:
        raise InvalidInput("observations must be a bounded JSON array")
    observed = {op: set() for op in operations}
    asserted = {op: set() for op in operations}
    counts = {op: 0 for op in operations}
    issues = []
    for index, record in enumerate(observations, 1):
        if (not isinstance(record, dict) or set(record) != {"operation", "status", "asserted"}
                or not isinstance(record["operation"], str) or len(record["operation"]) > 264
                or not _status_valid(record["status"]) or type(record["asserted"]) is not bool):
            issues.append({"code": "invalid_record", "row": index})
            continue
        op, status = record["operation"], record["status"]
        if op not in operations:
            issues.append({"code": "unknown_operation", "row": index})
            continue
        counts[op] += 1
        if not _declared(operations[op], status):
            issues.append({"code": "undocumented_status", "row": index})
            continue
        observed[op].add(status)
        if record["asserted"]:
            asserted[op].add(status)
    rows = []
    eligible = len(operations) - len(exclude)
    covered = 0
    for op in sorted(operations):
        missing = sorted(required.get(op, set()) - asserted[op])
        unasserted = sorted(observed[op] - asserted[op])
        if op in exclude:
            state = "excluded"
        elif not asserted[op]:
            state = "unasserted" if observed[op] else "unobserved"
            issues.append({"code": "no_asserted_response", "operation": op})
        elif missing:
            state = "missing_required"
        elif strict and unasserted:
            state = "unasserted_statuses"
        else:
            state = "covered"
        if op not in exclude and missing:
            issues.append({"code": "missing_required_statuses", "operation": op, "statuses": missing})
        if op not in exclude and strict and unasserted:
            issues.append({"code": "observed_status_not_asserted", "operation": op, "statuses": unasserted})
        if state == "covered":
            covered += 1
        rows.append({"operation": op, "state": state, "records": counts[op],
                     "observed_statuses": sorted(observed[op]),
                     "asserted_statuses": sorted(asserted[op]),
                     "unasserted_statuses": unasserted,
                     "missing_required_statuses": missing})
    scope = [[op, sorted(operations[op]), op in exclude, sorted(required.get(op, set()))]
             for op in sorted(operations)]
    scope_hash = hashlib.sha256(json.dumps({"operations": scope, "assert_all_observed": strict}, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    pin = {}
    if expected_scope_sha256 is not None:
        matches = expected_scope_sha256 == scope_hash
        pin["scope_pin"] = "matched" if matches else "mismatch"
        if not matches:
            issues.append({"code": "scope_fingerprint_mismatch"})
    return {"version": 1, "ok": not issues, "scope_sha256": scope_hash, **pin,
            "scope": "declared_paths_only", "assert_all_observed": strict,
            "summary": {"declared": len(operations), "excluded": len(exclude), "in_scope": eligible,
                        "covered": covered, "observations": len(observations), "issues": len(issues)},
            "operations": rows, "issues": issues}
