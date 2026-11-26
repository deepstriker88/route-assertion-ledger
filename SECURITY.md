# Security and privacy boundaries

Process only local, trusted, quiescent files. No URL fetch, request execution, proxy, environment access or upload. Reject unsupported paths and path-item references; JSON input is size/depth/container-bounded before parsing; duplicate keys and non-finite numbers are rejected. The observation format accepts only declared operation identifiers, numeric status and explicit boolean assertion flag. Unknown observation values and exclusion reasons are never emitted. The report includes declared route names, which may still be confidential. Do not submit actual URL paths, credentials, personal data or sensitive literal route names. No claim that assertions are authentic or sufficient. No authorization, payload/schema, parameter, header, query, live availability or security testing. JSON syntax and selected OpenAPI structures only, not complete specification validation. No YAML, Swagger 2.0, OpenAPI 3.2, partial path templates or external path-item resolution. HTML output escapes inserted text, contains no executable script and blocks external resources. Local memory is not erased or protected against other privileged processes. No independent external security certification is claimed.

Output and optional recorder evidence are created exclusively with mode 0600 on POSIX; zipapp mode 0700. The recorder writes only normalized operation/status/asserted triples and does not run HTTP requests. Do not reuse stale evidence across runs, and fail the pipeline when the actual test suite fails even if the coverage gate later passes. No tamper resistance or concurrency support. A failed write may leave a partial file; discard that run rather than reuse it. Windows ACL behavior is not verified.

2026-11-25: input reads compare regular-file identity, byte size and nanosecond
mtime/ctime before and after reading. Detected changes fail closed. This is
not an atomic snapshot or protection against a hostile concurrent writer.
The optional reviewed scope pin covers normalized operation/status rules and
effective policy, not test code, evidence content, signatures or free-text
exclusion reasons. Treat the expected fingerprint as a separately reviewed
configuration value. A successful pin must not replace ordinary tests.
