"""Optional local test-harness integration, never an HTTP client."""
import json
import os
from . import (InvalidInput, MAX_EVIDENCE_BYTES, MAX_OBSERVATIONS, METHODS,
               _route_shape, _status_valid)


def _check_operation(operation):
    if not isinstance(operation, str) or len(operation) > 264:
        raise InvalidInput("invalid operation identifier")
    method, sep, route = operation.partition(" ")
    if not sep or method not in METHODS:
        raise InvalidInput("invalid operation identifier")
    _route_shape(route)


class ObservationRecorder:
    """Write a new JSONL evidence file; record equality checks without Python assert.

    Use one recorder per serial test run. Not a thread/process-safe writer.
    """
    def __init__(self, path):
        self.path = path
        self._file = None
        self._count = self._bytes = 0
        self._used = False

    def __enter__(self):
        if self._used:
            raise InvalidInput("recorder cannot be reused")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            self._file = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        self._used = True
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._file is not None:
            try:
                self._file.close()
            finally:
                self._file = None
        return False

    def _record(self, operation, status, asserted):
        if self._file is None:
            raise InvalidInput("recorder is not open")
        _check_operation(operation)
        if not _status_valid(status):
            raise InvalidInput("invalid HTTP status")
        data = (json.dumps({"operation": operation, "status": status, "asserted": asserted},
                           ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        if self._count >= MAX_OBSERVATIONS or self._bytes + len(data) > MAX_EVIDENCE_BYTES:
            raise InvalidInput("evidence record or byte limit exceeded")
        self._file.write(data)
        self._file.flush()
        self._count += 1
        self._bytes += len(data)

    def observe(self, operation, status):
        """Record a response without claiming a test assertion."""
        self._record(operation, status, False)

    def assert_status(self, operation, actual, expected):
        """Record true only for an explicit successful equality check."""
        if not _status_valid(actual) or not _status_valid(expected):
            raise InvalidInput("invalid HTTP status")
        matched = actual == expected
        self._record(operation, actual, matched)
        if not matched:
            raise AssertionError("HTTP response status mismatch")
