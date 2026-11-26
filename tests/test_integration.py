import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from route_assertion_ledger import InvalidInput, load_observations_jsonl
from route_assertion_ledger.recording import ObservationRecorder
from test_ledger import spec, audit


class RecordingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / "evidence.jsonl"

    def test_success_and_unasserted(self):
        with ObservationRecorder(self.output) as r:
            r.assert_status("GET /items", 200, 200)
            r.assert_status("DELETE /items/{id}", 204, 204)
            r.observe("GET /items", 404)
        records = load_observations_jsonl(self.output.read_bytes())
        self.assertEqual([row["asserted"] for row in records], [True, True, False])
        self.assertTrue(audit(spec(), records)["ok"])
        self.assertFalse(audit(spec(), records, {"assert_all_observed": True})["ok"])
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)

    def test_mismatch_not_claimed_as_asserted(self):
        with self.assertRaises(AssertionError):
            with ObservationRecorder(self.output) as r:
                r.assert_status("GET /items", 500, 200)
        self.assertEqual(load_observations_jsonl(self.output.read_bytes()),
                         [{"operation": "GET /items", "status": 500, "asserted": False}])

    def test_mismatch_under_optimized_python(self):
        command = "import sys\nfrom route_assertion_ledger.recording import ObservationRecorder as R\nwith R(sys.argv[1]) as r:r.assert_status('GET /items',500,200)"
        p = subprocess.run([sys.executable, "-O", "-c", command, str(self.output)], capture_output=True, timeout=5)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(load_observations_jsonl(self.output.read_bytes())[0]["asserted"])

    def test_invalid_fields_no_record(self):
        with ObservationRecorder(self.output) as r:
            for op, status in [("GET https://private.test/x", 200), ("get /items", 200),
                               ("GET /items?secret=x", 200), ("GET /items", True), ("GET /items", 600)]:
                with self.assertRaises(InvalidInput):
                    r.observe(op, status)
            with self.assertRaises(InvalidInput):
                r.assert_status("GET /items", 200, False)
        self.assertEqual(self.output.read_bytes(), b"")

    def test_no_overwrite_or_reuse(self):
        recorder = ObservationRecorder(self.output)
        with recorder:
            recorder.observe("GET /items", 200)
        old = self.output.read_bytes()
        with self.assertRaises(InvalidInput):
            with recorder:
                pass
        with self.assertRaises(FileExistsError):
            with ObservationRecorder(self.output):
                pass
        self.assertEqual(self.output.read_bytes(), old)
        with self.assertRaises(InvalidInput):
            recorder.observe("GET /items", 200)

    def test_record_cap(self):
        with ObservationRecorder(self.output) as r:
            for _ in range(5000):
                r.observe("GET /items", 200)
            with self.assertRaises(InvalidInput):
                r.observe("GET /items", 200)
        self.assertEqual(len(load_observations_jsonl(self.output.read_bytes())), 5000)

    def test_byte_cap(self):
        op = "GET /" + "x" * 245
        with ObservationRecorder(self.output) as r:
            with self.assertRaises(InvalidInput):
                for _ in range(5000):
                    r.observe(op, 200)
        self.assertLessEqual(self.output.stat().st_size, 1024 * 1024)

    @unittest.skipUnless(os.name == "posix", "POSIX symlink check")
    def test_link_output_never_overwrites(self):
        target = self.root / "target.txt"
        target.write_text("unchanged")
        self.output.symlink_to(target)
        with self.assertRaises(FileExistsError):
            with ObservationRecorder(self.output):
                pass
        self.assertEqual(target.read_text(), "unchanged")


class ReviewScopeTests(unittest.TestCase):
    def test_pin_detects_review_scope_change_without_changing_coverage(self):
        model = spec()
        records = [{"operation":"GET /items","status":200,"asserted":True},
                   {"operation":"DELETE /items/{id}","status":204,"asserted":True}]
        approved = audit(model, records)["scope_sha256"]
        report = audit(model, records, expected_scope_sha256=approved)
        self.assertTrue(report["ok"])
        self.assertEqual(report["scope_pin"], "matched")
        changed = audit(model, records, {"required_statuses":{"GET /items":[200]}},
                        expected_scope_sha256=approved)
        self.assertFalse(changed["ok"])
        self.assertEqual(changed["summary"]["covered"], 2)
        self.assertEqual(changed["scope_pin"], "mismatch")
        self.assertIn({"code":"scope_fingerprint_mismatch"},changed["issues"])
        from route_assertion_ledger.report import html_report
        self.assertIn("Review scope changed", html_report(changed))
        self.assertNotIn("Coverage gate passed", html_report(changed))

    def test_malformed_pin_rejected(self):
        for value in ("", "x"*64, "A"*64, "0"*63, True, []):
            with self.subTest(value=value), self.assertRaises(InvalidInput):
                audit(spec(), [], expected_scope_sha256=value)

    def test_cli_pin_exit_and_json_contract(self):
        args = [sys.executable,"-m","route_assertion_ledger","examples/spec.json","examples/observations.json",
                "--policy","examples/policy.json"]
        base = subprocess.run(args, capture_output=True, timeout=10)
        scope = json.loads(base.stdout)["scope_sha256"]
        for pin, status, label in ((scope,1,"matched"),("0"*64,1,"mismatch"),("invalid",2,None)):
            result = subprocess.run(args+["--expected-scope-sha256",pin], capture_output=True, timeout=10)
            self.assertEqual(result.returncode,status)
            report = json.loads(result.stdout)
            if label:
                self.assertEqual(report["scope_pin"],label)

    def test_input_metadata_mutation_and_link_rejection(self):
        from route_assertion_ledger.__main__ import read_input
        from unittest.mock import patch
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"source.json"
            path.write_text("{}")
            self.assertEqual(read_input(path,100),{})
            real_fstat=os.fstat
            calls=0
            def change(fd):
                nonlocal calls
                original=real_fstat(fd)
                calls+=1
                if calls==2:
                    return SimpleNamespace(st_dev=original.st_dev,st_ino=original.st_ino,
                        st_size=original.st_size,st_mtime_ns=original.st_mtime_ns+1,
                        st_ctime_ns=original.st_ctime_ns,st_mode=original.st_mode)
                return original
            with patch("route_assertion_ledger.__main__.os.fstat",side_effect=change):
                with self.assertRaises(InvalidInput):
                    read_input(path,100)
            with self.assertRaises(InvalidInput):
                read_input(path,1)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux output failure fixture")
    def test_output_failure_has_no_traceback(self):
        with open("/dev/full","wb") as target:
            result=subprocess.run([sys.executable,"-m","route_assertion_ledger","examples/spec.json",
                "examples/observations.json"], stdout=target,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(result.returncode,2)
        self.assertNotIn(b"Traceback",result.stderr)


class PackageTests(unittest.TestCase):
    def test_reproducible_package_and_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = (Path(tmp) / name for name in ("a.pyz", "b.pyz"))
            for path in (a, b):
                subprocess.run([sys.executable, "build_zipapp.py", str(path)], check=True, timeout=10)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with zipfile.ZipFile(a) as z:
                self.assertEqual(set(z.namelist()), {"LICENSE", "__main__.py", "route_assertion_ledger/__init__.py",
                    "route_assertion_ledger/__main__.py", "route_assertion_ledger/recording.py",
                    "route_assertion_ledger/report.py","route_assertion_ledger/preflight.py","route_assertion_ledger/desktop.py","route_assertion_ledger/desktop_ui.py"})
            p = subprocess.run([sys.executable, str(a), "examples/spec.json", "examples/observations.json",
                                "--policy", "examples/policy.json"], capture_output=True, timeout=10)
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertEqual(json.loads(p.stdout)["summary"]["covered"], 2)
            preflight = subprocess.run([sys.executable, str(a), "--preflight", "examples/spec.json"],
                                       capture_output=True, timeout=10)
            self.assertEqual(preflight.returncode, 0, preflight.stderr)
            self.assertEqual(json.loads(preflight.stdout)["mode"], "spec_preflight")

            original = a.read_bytes()
            p = subprocess.run([sys.executable, "build_zipapp.py", str(a)], capture_output=True, timeout=10)
            self.assertNotEqual(p.returncode, 0)
            self.assertEqual(original, a.read_bytes())

    def test_report_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.html"
            p = subprocess.run([sys.executable, "-m", "route_assertion_ledger", "examples/spec.json",
                                "examples/observations.json", "--html", str(output)], capture_output=True, timeout=10)
            self.assertIn(p.returncode, (0, 1))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
