"""Bounded, local spec inventory. Does not resolve references or send requests."""
from collections import Counter
from . import InvalidInput, METHODS, _VERSION

MAX_DOCUMENTS = 8
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_FINDINGS = 500
MAX_SCAN_NODES = 100000
MAX_POINTER_CHARS = 1024
MAX_ALL_OPERATIONS = 5000
_INLINE_METHODS = frozenset(m.lower() for m in METHODS)


def _child(pointer, key):
    value = pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")
    if len(value) > MAX_POINTER_CHARS or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise InvalidInput("unsupported or oversized JSON pointer")
    return value


def _supported(spec):
    return isinstance(spec, dict) and (
        (isinstance(spec.get("openapi"), str) and _VERSION.fullmatch(spec["openapi"]) and "swagger" not in spec)
        or (spec.get("swagger") == "2.0" and "openapi" not in spec)
    )


def preflight(specs):
    """Inventory literal $refs and duplicate explicit inline operationIds.

    Reports locations only: document number and JSON pointer. Does not return
    reference strings, operationId strings, file paths, or example values.
    All findings require review; a clean scan is not full spec validation.
    """
    if not isinstance(specs, (list, tuple)) or not 1 <= len(specs) <= MAX_DOCUMENTS:
        raise InvalidInput("choose 1 to 8 local spec documents")
    findings, counts = [], Counter()
    ids = {}
    nodes = operations = 0

    def mark(code, **location):
        counts[code] += 1
        if len(findings) < MAX_FINDINGS:
            findings.append({"code": code, **location})

    def scan(node, doc, pointer="", depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_SCAN_NODES or depth > 64:
            raise InvalidInput("spec scan budget exceeded")
        if isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(key, str):
                    raise InvalidInput("object keys must be strings")
                path = _child(pointer, key)
                if key == "$ref":
                    if not isinstance(value, str) or not value or any(c.isspace() or ord(c)<32 or ord(c)==127 or 0xD800<=ord(c)<=0xDFFF for c in value):
                        mark("AMBIGUOUS_REF", document=doc, pointer=path)
                    elif not value.startswith("#"):
                        mark("EXTERNAL_REF", document=doc, pointer=path)
                scan(value, doc, path, depth + 1)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                scan(value, doc, _child(pointer, i), depth + 1)

    for doc, spec in enumerate(specs, 1):
        if not _supported(spec):
            raise InvalidInput("OpenAPI 3.0/3.1 or Swagger 2.0 JSON required")
        paths = spec.get("paths")
        if not isinstance(paths, dict):
            raise InvalidInput("paths object required for inline operation scan")
        scan(spec, doc)
        before_operations=operations
        before_path_refs=counts["PATH_ITEM_REF_NOT_EXPANDED"]
        if not paths:
            mark("NO_INLINE_PATHS", document=doc, pointer="/paths")
        for path, item in paths.items():
            if isinstance(path, str) and path.startswith("x-"):
                continue
            if not isinstance(path, str) or not path.startswith("/") or not isinstance(item, dict):
                raise InvalidInput("invalid inline path item")
            loc = _child("/paths", path)
            if "$ref" in item:
                mark("PATH_ITEM_REF_NOT_EXPANDED", document=doc, pointer=_child(loc, "$ref"))
                continue
            for method, op in item.items():
                if method not in _INLINE_METHODS:
                    continue
                operations += 1
                if operations > MAX_ALL_OPERATIONS:
                    raise InvalidInput("operation inventory limit exceeded")
                if not isinstance(op, dict):
                    raise InvalidInput("invalid inline operation")
                if "operationId" not in op:
                    continue
                opid = op["operationId"]
                pointer = _child(_child(loc, method), "operationId")
                if not isinstance(opid, str) or not opid.strip() or len(opid)>1024 or any(ord(c)<32 or ord(c)==127 or 0xD800<=ord(c)<=0xDFFF for c in opid):
                    mark("INVALID_OPERATION_ID", document=doc, pointer=pointer)
                    continue
                ids.setdefault(opid, []).append((doc, pointer))

        if paths and before_operations==operations and before_path_refs==counts["PATH_ITEM_REF_NOT_EXPANDED"]:
            mark("NO_INLINE_OPERATIONS",document=doc,pointer="/paths")

    duplicate_groups = 0
    for group in ids.values():
        if len(group) < 2:
            continue
        duplicate_groups += 1
        for doc, pointer in group:
            mark("DUPLICATE_OPERATION_ID", document=doc, pointer=pointer, group=duplicate_groups)
    total = sum(counts.values())
    return {
        "version":1, "mode":"spec_preflight", "ok":total == 0,
        "documents":len(specs), "inline_operations":operations,
        "duplicate_id_groups":duplicate_groups,
        "finding_count":total, "counts":{k:v for k,v in sorted(counts.items()) if v},
        "findings":findings, "truncated":total > len(findings),
        "scope":"Literal $ref inventory and explicit operationId collisions in inline paths only. No reference resolution or OpenAPI validation."
    }
