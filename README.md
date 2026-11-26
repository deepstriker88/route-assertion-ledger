# Route Assertion Ledger

## Desktop quick start

Build or obtain the reviewed `route-assertion-ledger.pyz` file. On Windows with
Python installed, open PowerShell in its directory and run:

    py route-assertion-ledger.pyz --gui

On Linux/macOS:

    python3 route-assertion-ledger.pyz --gui

Choose local inputs, click Run check, or Try example to run a real synthetic
fixture. View report shows the selected findings; Save report writes a new JSON or script-free HTML file
only. The interface never uploads inputs or launches a payment flow. Tkinter
must be available in your Python installation (it is optional on some Linux
distributions). If unavailable or on a headless machine, use the existing CLI.
The CLI needs no GUI dependencies. The GUI is a desktop interface, not a mobile
browser inspector. Free local edition; no paid plan or subscription.


MIT-licensed local utility. No hosted or paid service.

## What it does

Checks whether a test suite's supplied assertion records cover declared OpenAPI operations and selected response statuses. It never sends requests or consumes HTTP bodies. A recorded observation without an explicit assertion does not count as covered.

## Quick start

Python 3.10+; no installation or runtime dependency required. Run from this product directory:

    python3 -m route_assertion_ledger examples/spec.json examples/observations.json --policy examples/policy.json --html report.html

The included scenario returns exit 1 because GET /items/{id} has an observed but unasserted 404. Open the generated HTML file locally. A subsequent run must use a new output filename (no overwrite).

## Common examples

Build a standalone zipapp (new filename required; reproducible bytes for the same Python/zlib build environment):

    python3 build_zipapp.py route-assertion-ledger.pyz
    python3 route-assertion-ledger.pyz examples/spec.json examples/observations.json --policy examples/policy.json

JSONL is also accepted with --observations-format jsonl, one normalized object per line. An observation is exactly {"operation":"GET /items/{id}","status":404,"asserted":true}. Use the exact declared path template, not an actual URL. The optional policy is an object with required_statuses mapping known operations to concrete numeric HTTP codes exclude mapping known operations to a nonempty rationale, and optional assert_all_observed=true to require assertions for every observed documented status. Excluded operations remain visible; all-excluded policy fails.

## Record assertions from a Python test

    from route_assertion_ledger.recording import ObservationRecorder

    with ObservationRecorder("run-evidence.jsonl") as evidence:
        # actual_status is supplied by your own test client.
        evidence.assert_status("GET /items", actual=200, expected=200)
        evidence.observe("GET /items/{id}", 404)

    # Then run the gate using --observations-format jsonl.

The recorder compares concrete integer HTTP statuses, records false on a mismatch, and raises AssertionError even under python -O. The example numbers are illustrative; use actual test-client values in real integration. The file is created exclusively, not appended to prior test runs. One recorder per serial test run; no concurrent writer or automatic HTTP interception. The ordinary test suite must pass independently before the coverage gate is accepted. This is not proof of network execution.

## API

audit(spec, observations, policy=None) returns a deterministic Python dictionary. CLI JSON output includes counts, declared operation names, observed/explicitly asserted statuses, missing required statuses, privacy-minimized issue codes and a SHA-256 scope fingerprint. Scope fingerprint represents normalized route/status declarations and effective policy (excluding free-text reasons), not the input file, execution proof or signed attestation. All nonexcluded operations must have at least one declared asserted status; selected required statuses must also be asserted. In strict mode, every observed documented status requires an assertion. Default mode reports but does not fail extra unasserted statuses unless explicitly required. Invalid observations and undocumented statuses fail even for excluded operations. Exit codes: 0 pass, 1 findings, 2 invalid configuration/input/output.

### Pin a reviewed scope

Record the scope fingerprint only after separately reviewing the route/status
declarations and policy. Save the approved 64-character lowercase SHA-256
outside the generated report, then pass it as --expected-scope-sha256 VALUE.
A mismatch produces a finding (exit 1), even if every current operation is
covered. The optional API keyword expected_scope_sha256 behaves the same.
Malformed pins are invalid input (exit 2). Do not derive the expected value
from the current unreviewed input in the same CI run.
This is a review-scope check, not proof of test execution or evidence freshness.

## Requirements

Python 3.10 or newer. OpenAPI 3.0/3.1 JSON; 512 KiB spec, 1 MiB evidence, 256 KiB policy, 1,000 operations, 5,000 declared responses and 5,000 records, JSON nesting depth 64 and 50,000 containers per input. No server or third-party libraries. See VALIDATION.md and run python3 benchmarks/run.py to reproduce the synthetic benchmark.

## Security and limitations

See SECURITY.md. No live traffic, credentials, raw URLs, headers or request/response payloads. Report includes declared route names only; review before sharing. Exact declared template matching, no trailing-slash/percent-encoded/Unicode routes, no YAML, no path references, no partial-segment templates, no response schema validation. Not a full OpenAPI validator. Assertion flags are user-supplied claims, not proof; exclusions require independent review.

## Troubleshooting

Exit 2: check JSON, sizes, route templates, policy and whether HTML output already exists. Exit 1: inspect issue codes and missing required statuses. An unasserted observation does not meet the gate. Do not add fabricated assertion records to pass CI.


## Spec inventory before checking assertion evidence (review candidate)

Use the same zipapp without assertion records to locate literal external or
ambiguous `$ref` occurrences and duplicate explicit `operationId` strings:

    python3 route-assertion-ledger.pyz --preflight service-a.json service-b.json

Desktop: select **Spec preflight** under Check type, choose 1–8 JSON spec files,
then Run check. The assertion-evidence fields are hidden in this mode; Try example
uses a synthetic duplicate-ID and external-reference example.

Accepts 1–8 OpenAPI 3.0/3.1 or Swagger 2.0 UTF-8 JSON documents; 512 KiB each,
4 MiB aggregate maximum. Inline operations are counted; missing IDs are not
inferred, and path-item references are flagged without expansion. Literal
`$ref` keys are inventoried even in examples/extensions (may be data).
The report uses document numbers and JSON pointers, not raw reference values,
operation IDs or filenames. Group numbers connect duplicate-ID locations.
No references are followed. No URL, file or network access based on input
content. This is not a full OpenAPI validator, not a security verdict, and does
not resolve fragments or inspect OpenAPI 3.1 dynamic references. Exit 0 means
no findings in this limited scan, 1 means review required, 2 means input error.
The report caps displayed findings at 500 and retains exact bounded counts.
Spec inventory is available in both CLI and desktop modes; the existing
assertion coverage workflow remains available.


## Installation and support

Extract the complete download ZIP; Windows uses the provided launcher or `py -3 -I -B route-assertion-ledger.pyz --gui`. The CLI does not need Tkinter.

Use synthetic or redacted inputs in bug reports. Optional support: https://buymeacoffee.com/eztoolgo (no entitlement or subscription).

## License

MIT; see LICENSE.

## Download and run

Download the versioned local ZIP from the GitHub release, extract the full archive and open index.html. No account or subscription is required.
