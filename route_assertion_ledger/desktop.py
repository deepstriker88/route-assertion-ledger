"""Local GUI adapter for normalized assertion coverage, not network traffic."""
import sys
from . import MAX_SPEC_BYTES, MAX_EVIDENCE_BYTES, MAX_POLICY_BYTES, InvalidInput, audit
from .__main__ import read_input
from .desktop_ui import Field,Result,launch
from .preflight import preflight, MAX_DOCUMENTS, MAX_TOTAL_BYTES

TITLE="Route Assertion Ledger"
LEAD="Review API specifications or find missing response assertions before CI release."
LIMIT="Local checks only. Neither preflight nor assertion coverage proves complete specification validity, security or test execution."
MORE="""FREE LOCAL TOOL · $0

Choose Assertion coverage for OpenAPI 3.0/3.1 JSON and normalized assertion records:
{"operation":"GET /items/{id}","status":404,"asserted":true}

Use the declared path template, not a real URL. JSON arrays and JSONL are
supported. Optional policy specifies required concrete statuses, reviewed
exclusions and whether every observed status must be asserted. An optional
reviewed scope SHA-256 pin detects changes to declarations and effective policy.

This is an offline coverage gate, not a full OpenAPI validator or a
traffic-capture product. No requests are sent. No payloads, headers, or
credentials are accepted. Test harness evidence must be trustworthy and the
ordinary test suite must independently pass. No YAML, path references,
partial-segment templates or real URL matching.

Spec preflight instead selects 1–8 JSON documents (up to 4 MiB total),
including Swagger 2.0, and inventories literal external references and duplicate
operationIds without resolving references. Reports include document numbers and
JSON pointers; review declared names before sharing.

Coverage limits: 512 KiB spec, 1 MiB evidence, 256 KiB policy, 1,000 operations,
5,000 responses and records. Reports may contain declared route names.
Review before sharing. Use a separate trusted test runner.
"""
CONDITIONAL_FIELDS=("spec","specs","evidence")
FIELDS=(
    Field("mode","Check type","choice",choices=("Assertion coverage","Spec preflight"),default="Assertion coverage"),
    Field("specs","Spec files","files",optional=True,maximum=MAX_DOCUMENTS,filters=(("JSON","*.json"),("All files","*"))),
    Field("spec","OpenAPI JSON","file",optional=True,filters=(("JSON","*.json"),("All files","*"))),
    Field("evidence","Assertion records","file",optional=True,filters=(("Evidence","*.json *.jsonl"),("All files","*"))),
    Field("format","Evidence format","choice",choices=("JSON","JSONL"),default="JSON"),
    Field("policy","JSON policy","file",optional=True,filters=(("JSON","*.json"),("All files","*"))),
    Field("pin","Scope SHA-256","text",optional=True),
)


def describe(data):
    s=data["summary"]
    details=[]
    for row in sorted(data["operations"],key=lambda x:(x["state"] in ("covered","excluded"),x["operation"])):
        missing=" · missing "+", ".join(map(str,row["missing_required_statuses"])) if row["missing_required_statuses"] else ""
        details.append(row["operation"]+" · "+row["state"].replace("_"," ")+missing)
    other=[issue["code"].replace("_"," ")+(" · record "+str(issue["row"]) if "row" in issue else "") for issue in data["issues"] if "operation" not in issue]
    details=other+details
    return Result("pass" if data["ok"] else "review","Assertion checks passed" if data["ok"] else "Missing assertion evidence",
                  "Only declared operations and supplied assertion records are evaluated.",
                  (("Covered",f"{s['covered']}/{s['in_scope']}"),("Excluded",s["excluded"]),("Findings",s["issues"])),
                  tuple(details),data)


def visible_for_mode(values):
    if values.get("mode")=="Spec preflight":return ("mode","specs")
    return ("mode","spec","evidence","format","policy","pin")


def required_for_mode(values):
    return ("specs",) if values.get("mode")=="Spec preflight" else ("spec","evidence")


def describe_preflight(data):
    details=[]
    for finding in data["findings"]:
        text=f"Document {finding['document']} · {finding['code'].replace('_',' ').lower()} · {finding['pointer']}"
        if "group" in finding:text+=f" · group {finding['group']}"
        details.append(text)
    if data["truncated"]:details.append("Finding display capped; counts include all findings.")
    return Result("pass" if data["ok"] else "review",
                  "No preflight findings" if data["ok"] else "Spec preflight review",
                  "Literal reference and inline operation ID inventory only; no reference resolution.",
                  (("Documents",data["documents"]),("Operations",data["inline_operations"]),("Findings",data["finding_count"])),
                  tuple(details),data)


def run(values):
    if values.get("mode","Assertion coverage")=="Spec preflight":
        paths=values.get("specs")
        if not isinstance(paths,(tuple,list)) or not 1<=len(paths)<=MAX_DOCUMENTS or len(paths)*MAX_SPEC_BYTES>MAX_TOTAL_BYTES:
            raise InvalidInput("choose 1 to 8 bounded spec documents")
        return describe_preflight(preflight([read_input(path,MAX_SPEC_BYTES) for path in paths]))
    if values.get("mode","Assertion coverage")!="Assertion coverage":
        raise InvalidInput("invalid check type")
    if values["format"] not in ("JSON","JSONL"):raise InvalidInput("invalid evidence format")
    spec=read_input(values["spec"],MAX_SPEC_BYTES)
    records=read_input(values["evidence"],MAX_EVIDENCE_BYTES,jsonl=values["format"]=="JSONL")
    policy=read_input(values["policy"],MAX_POLICY_BYTES) if values.get("policy") else None
    if values.get("policy") and policy is None:raise InvalidInput("policy must be an object")
    return describe(audit(spec,records,policy,expected_scope_sha256=values.get("pin") or None))


def demo_data():
    spec={"openapi":"3.1.0","paths":{"/items":{"get":{"responses":{"200":{}}}},"/items/{id}":{"get":{"responses":{"200":{},"404":{}}}}}}
    records=[{"operation":"GET /items","status":200,"asserted":True},{"operation":"GET /items/{id}","status":200,"asserted":True},{"operation":"GET /items/{id}","status":404,"asserted":False}]
    policy={"required_statuses":{"GET /items/{id}":[404]},"assert_all_observed":True}
    return spec,records,policy


def demo():
    return describe(audit(*demo_data()))


def demo_for_mode(values):
    if values.get("mode")!="Spec preflight":return demo()
    return describe_preflight(preflight([
        {"openapi":"3.1.0","paths":{"/a":{"get":{"operationId":"listItems"}}}},
        {"openapi":"3.1.0","paths":{"/b":{"get":{"operationId":"listItems","responses":{"200":{"$ref":"other.json#/Response"}}}}}},
    ]))


def main():
    try:
        launch(sys.modules[__name__]);return 0
    except ImportError:
        print("Desktop UI needs Python Tkinter. Use the CLI without --gui.",file=sys.stderr);return 2
    except Exception as e:
        if type(e).__name__=="TclError":
            print("Desktop display unavailable. Use the CLI without --gui.",file=sys.stderr);return 2
        raise
