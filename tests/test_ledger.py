import copy
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from route_assertion_ledger import audit, load_json, load_observations_jsonl, InvalidInput, MAX_SPEC_BYTES
from route_assertion_ledger.report import html_report


def spec():
    return {"openapi":"3.1.2", "paths":{"/items":{"get":{"responses":{
        "200":{"description":"OK"}, "4XX":{"description":"Bad request"}, "default":{"description":"Other"}}}},
        "/items/{id}":{"delete":{"responses":{"204":{},"404":{}}}}}}


def row(op="GET /items", status=200, asserted=True):
    return {"operation":op,"status":status,"asserted":asserted}


def good():
    return [row(), row("DELETE /items/{id}",204)]


class GateTests(unittest.TestCase):
    def test_complete_pass(self):
        r=audit(spec(),good())
        self.assertTrue(r["ok"])
        self.assertEqual(r["summary"]["covered"],2)
    def test_unobserved_fails(self):
        r=audit(spec(),[row()])
        self.assertFalse(r["ok"])
        self.assertEqual(r["operations"][0]["state"],"unobserved")
    def test_observed_is_not_asserted(self):
        r=audit(spec(),[row(asserted=False),good()[1]])
        self.assertFalse(r["ok"])
        self.assertEqual(r["operations"][1]["state"],"unasserted")
    def test_required_status_unasserted(self):
        r=audit(spec(),good()+[row(status=404,asserted=False)],
                {"required_statuses":{"GET /items":[200,404]}})
        self.assertFalse(r["ok"])
        self.assertEqual(r["operations"][1]["missing_required_statuses"],[404])
    def test_all_observed_mode(self):
        records=good()+[row(status=404,asserted=False)]
        self.assertTrue(audit(spec(),records)["ok"])
        r=audit(spec(),records,{"assert_all_observed":True})
        self.assertFalse(r["ok"])
        self.assertEqual(r["operations"][1]["unasserted_statuses"],[404])
        self.assertEqual(r["operations"][1]["state"],"unasserted_statuses")
        self.assertTrue(audit(spec(),records+[row(status=404)],{"assert_all_observed":True})["ok"])
        self.assertNotEqual(audit(spec(),records)["scope_sha256"],r["scope_sha256"])
        with self.assertRaises(InvalidInput):audit(spec(),records,{"assert_all_observed":1})
    def test_jsonl_matches_array_and_rejects_bad_lines(self):
        data=b"\n".join(json.dumps(r).encode() for r in good())+b"\n"
        self.assertEqual(load_observations_jsonl(data),good())
        self.assertEqual(load_observations_jsonl(data.replace(b"\n",b"\r\n")),good())
        self.assertEqual(load_observations_jsonl(b""),[])
        for raw in (b"\n",b"{}\n\n{}",b'{"a":1,"a":2}',b" "*8193,b"{}\n"*5001):
            with self.assertRaises(InvalidInput):load_observations_jsonl(raw)
    def test_required_status_asserted(self):
        self.assertTrue(audit(spec(),good()+[row(status=404)],
                {"required_statuses":{"GET /items":[200,404]}})["ok"])
    def test_range_and_default(self):
        self.assertTrue(audit(spec(),good()+[row(status=418),row(status=503)])["ok"])
    def test_undocumented_status_even_when_asserted(self):
        r=audit(spec(),good()+[row("DELETE /items/{id}",500)])
        self.assertFalse(r["ok"])
        self.assertIn({"code":"undocumented_status","row":3},r["issues"])
    def test_unknown_operation_privacy(self):
        marker="GET /items/PRIVATE-CUSTOMER-867"
        r=audit(spec(),good()+[row(marker)])
        self.assertFalse(r["ok"])
        self.assertNotIn(marker,json.dumps(r))
        self.assertNotIn(marker,html_report(r))
    def test_extra_input_fields_not_echoed(self):
        bad=row()
        bad["headers"]={"Authorization":"sensitive-example-value"}
        r=audit(spec(),good()+[bad])
        self.assertEqual(r["issues"],[{"code":"invalid_record","row":3}])
        self.assertNotIn("sensitive-example-value",json.dumps(r))
    def test_invalid_record_types(self):
        for rec in (None,[],{},row(status=True),row(status=200.0),row(status=99),row(status=600),
                    row(asserted="true"),row(op=1),row(op="x"*265)):
            with self.subTest(rec=type(rec).__name__):
                r=audit(spec(),good()+[rec])
                self.assertIn({"code":"invalid_record","row":3},r["issues"])
    def test_exclusion_visible_and_reason_omitted(self):
        r=audit(spec(),[row()],{"exclude":{"DELETE /items/{id}":"private reason 123"}})
        self.assertTrue(r["ok"])
        self.assertEqual(r["summary"]["excluded"],1)
        self.assertNotIn("private reason 123",json.dumps(r))
        self.assertEqual(r["operations"][0]["state"],"excluded")
    def test_excluded_undocumented_status_still_fails(self):
        r=audit(spec(),[row(),row("DELETE /items/{id}",500)],
                {"exclude":{"DELETE /items/{id}":"not in release scope"}})
        self.assertFalse(r["ok"])
    def test_all_excluded_rejected(self):
        with self.assertRaises(InvalidInput):
            audit(spec(),[],{"exclude":{"DELETE /items/{id}":"a","GET /items":"b"}})
    def test_bad_policy(self):
        cases=[[],{"unknown":{}},{"exclude":{"GET /other":"a"}},
               {"exclude":{"GET /items":" "}},{"required_statuses":{"GET /items":[]}},
               {"required_statuses":{"GET /items":[200,200]}},
               {"required_statuses":{"GET /items":[True]}},
               {"required_statuses":{"DELETE /items/{id}":[500]}},
               {"exclude":{"GET /items":"a"},"required_statuses":{"GET /items":[200]}}]
        for p in cases:
            with self.assertRaises(InvalidInput):audit(spec(),good(),p)
    def test_version_scope(self):
        for version in ("3.0.4","3.1.2"):
            doc=spec();doc["openapi"]=version
            self.assertTrue(audit(doc,good())["ok"])
        for version in ("3.2.1","2.0","3.1","3.1.2 trailing",None):
            doc=spec();doc["openapi"]=version
            with self.assertRaises(InvalidInput):audit(doc,good())
    def test_reject_unsupported_paths(self):
        for path in ("/a//b","/a/","/x/{id}.json","/x/{id}/{id}","/x/..","/x?q=a",
                     "https://example.org/x","/x/%2F","/x/한글","/x/<script>","/x/{}"):
            doc=spec();doc["paths"][path]={"get":{"responses":{"200":{}}}}
            with self.assertRaises(InvalidInput):audit(doc,good())
    def test_identical_template_shape_rejected(self):
        doc=spec();doc["paths"]["/items/{other}"]={"get":{"responses":{"200":{}}}}
        with self.assertRaises(InvalidInput):audit(doc,good())
    def test_concrete_and_templated_paths_are_distinct(self):
        doc=spec();doc["paths"]["/items/active"]={"get":{"responses":{"200":{}}}}
        r=audit(doc,good()+[row("GET /items/active")])
        self.assertTrue(r["ok"])
    def test_root_path(self):
        doc={"openapi":"3.0.4","paths":{"/":{"get":{"responses":{"200":{}}}}}}
        self.assertTrue(audit(doc,[row("GET /")])["ok"])
    def test_unresolved_path_ref_rejected(self):
        doc=spec();doc["paths"]["/items"]={"$ref":"other.json"}
        with self.assertRaises(InvalidInput):audit(doc,good())
    def test_response_ref_keys_supported_without_loading_target(self):
        doc=spec();doc["paths"]["/items"]["get"]["responses"]["200"]={"$ref":"outside.json"}
        self.assertTrue(audit(doc,good())["ok"])
    def test_invalid_response_declarations(self):
        for responses in ({},{"x-note":{}},{"600":{}},{"2xx":{}},{"200":[]},{"200":None}):
            doc=spec();doc["paths"]["/items"]["get"]["responses"]=responses
            with self.assertRaises(InvalidInput):audit(doc,good())
    def test_invalid_method(self):
        doc=spec();doc["paths"]["/items"]["GET"]={"responses":{"200":{}}}
        with self.assertRaises(InvalidInput):audit(doc,good())
    def test_empty_spec(self):
        for doc in ({},[],{"openapi":"3.1.0","paths":{}},{"openapi":"3.1.0","paths":{"/x":{}}}):
            with self.assertRaises(InvalidInput):audit(doc,[])
    def test_json_duplicate_rejected(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":{"y":1,"y":2}}',b'{"x":NaN}',b'\xff',b'[[['):
            with self.assertRaises(InvalidInput):load_json(raw,1000)
    def test_json_bom_and_limit(self):
        self.assertEqual(load_json(b'\xef\xbb\xbf{"a":1}',20),{"a":1})
        with self.assertRaises(InvalidInput):load_json(b" "*101,100)
    def test_deep_json(self):
        with self.assertRaises(InvalidInput):load_json(b"["*1500+b"0"+b"]"*1500,5000)
    def test_json_structure_strings_and_finite_numbers(self):
        value={"text":"[{"*1000+'quoted"\\tail'}
        self.assertEqual(load_json(json.dumps(value).encode(),10000),value)
        with self.assertRaises(InvalidInput):load_json(b'{"n":1e999}',100)
        with self.assertRaises(InvalidInput):load_json(b'['+b'[],'*50001+b'[]]',200000)
        self.assertEqual(load_json(b'['*64+b'0'+b']'*64,1000)[0][0][0][0] is not None,True)
        with self.assertRaises(InvalidInput):load_json(b'['*65+b'0'+b']'*65,1000)
    def test_direct_api_non_string_keys(self):
        for doc in ({"openapi":"3.1.0","paths":{1:{}}},
                    {"openapi":"3.1.0","paths":{"/x":{1:{}}}},
                    {"openapi":"3.1.0","paths":{"/x":{"get":{"responses":{200:{}}}}}}):
            with self.assertRaises(InvalidInput):audit(doc,[])
    def test_observation_cap(self):
        with self.assertRaises(InvalidInput):audit(spec(),[row()]*5001)
    def test_operation_cap(self):
        doc={"openapi":"3.1.0","paths":{f"/x{i}":{"get":{"responses":{"200":{}}}} for i in range(1001)}}
        with self.assertRaises(InvalidInput):audit(doc,[])
    def test_scope_fingerprint_order_and_assertions(self):
        a=spec();b=copy.deepcopy(a);b["paths"]=dict(reversed(list(b["paths"].items())))
        one=audit(a,good());two=audit(b,list(reversed(good())))
        self.assertEqual(one["scope_sha256"],two["scope_sha256"])
        self.assertEqual(one["scope_sha256"],audit(a,[])["scope_sha256"])
        self.assertNotEqual(one["scope_sha256"],audit(a,good(),{"required_statuses":{"GET /items":[200]}})["scope_sha256"])
    def test_repeated_assertions_do_not_inflate_coverage(self):
        r=audit(spec(),good()+[row()]*20)
        self.assertEqual(r["summary"]["covered"],2)
        self.assertEqual(r["operations"][1]["asserted_statuses"],[200])
    def test_html_is_local_and_safe(self):
        r=audit(spec(),good()+[row("GET /x/<script>alert(1)</script>")])
        html=html_report(r)
        self.assertNotIn("<script",html)
        self.assertNotIn("alert(1)",html)
        self.assertIn("default-src 'none'",html)
        self.assertIn("Coverage gaps found",html)
    def test_html_prioritizes_gaps_and_collapses_covered(self):
        result=audit(spec(),good(),{"required_statuses":{"GET /items":[200,404]}})
        html=html_report(result)
        self.assertIn('class="gap"',html)
        self.assertIn("Required status not asserted",html)
        self.assertIn("<summary>Covered operations (1)</summary>",html)
        self.assertLess(html.index("Needs attention"),html.index("Covered operations"))
        self.assertLess(html.index("Validation issues"),html.index("Covered operations"))
        self.assertIn("Excluded operations: 0",html)
    def test_html_covered_and_excluded_states(self):
        result=audit(spec(),[row()],{"exclude":{"DELETE /items/{id}":"PRIVATE-REASON"}})
        html=html_report(result)
        self.assertIn("Coverage gate passed",html)
        self.assertIn("<summary>Excluded by policy (1)</summary>",html)
        self.assertNotIn("PRIVATE-REASON",html)
        self.assertNotIn("Needs attention",html)
    def test_random_reference_model(self):
        rng=random.Random(719)
        for _ in range(100):
            records=[]
            expected=set()
            for i in range(rng.randrange(20)):
                op=rng.choice(["GET /items","DELETE /items/{id}"])
                status=rng.choice([200,204,404,500])
                asserted=rng.choice([True,False])
                records.append(row(op,status,asserted))
                if asserted and (op=="GET /items" or status in (204,404)):
                    expected.add(op)
            r=audit(spec(),records)
            self.assertEqual(r["summary"]["covered"],len(expected))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.spec=self.root/"spec.json";self.spec.write_text(json.dumps(spec()))
        self.records=self.root/"records.json";self.records.write_text(json.dumps(good()))
        self.cmd=[sys.executable,"-m","route_assertion_ledger",str(self.spec),str(self.records)]
    def run_cli(self,*args):
        return subprocess.run(self.cmd+list(args),capture_output=True,text=True,timeout=5)
    def test_pass_and_non_overwrite(self):
        report=self.root/"report.html"
        p=self.run_cli("--html",str(report))
        self.assertEqual(p.returncode,0,p.stderr)
        original=report.read_bytes()
        p=self.run_cli("--html",str(report))
        self.assertEqual(p.returncode,2)
        self.assertEqual(report.read_bytes(),original)
    def test_finding_exit(self):
        self.records.write_text("[]")
        p=self.run_cli()
        self.assertEqual(p.returncode,1)
        self.assertFalse(json.loads(p.stdout)["ok"])
    def test_malformed_exit_safe(self):
        self.records.write_text('{"PRIVATE-TEST-SENTINEL":')
        p=self.run_cli()
        self.assertEqual(p.returncode,2)
        self.assertNotIn("PRIVATE-TEST-SENTINEL",p.stdout+p.stderr)
    def test_jsonl_cli(self):
        self.records.write_text("\n".join(json.dumps(r) for r in good())+"\n")
        self.assertEqual(self.run_cli("--observations-format","jsonl").returncode,0)
        self.assertEqual(self.run_cli().returncode,2)
    def test_policy_null_rejected(self):
        p=self.root/"policy.json";p.write_text("null")
        self.assertEqual(self.run_cli("--policy",str(p)).returncode,2)
    def test_reject_symlink(self):
        if not hasattr(os,"symlink"):self.skipTest("links unsupported")
        link=self.root/"link.json"
        try:link.symlink_to(self.records)
        except OSError:self.skipTest("links unavailable")
        self.cmd[-1]=str(link)
        self.assertEqual(self.run_cli().returncode,2)
    @unittest.skipUnless(hasattr(os,"mkfifo"),"POSIX FIFO")
    def test_fifo_rejected_without_wait(self):
        fifo=self.root/"fifo";os.mkfifo(fifo)
        self.cmd[-1]=str(fifo)
        self.assertEqual(self.run_cli().returncode,2)
    def test_oversize_input(self):
        self.spec.write_bytes(b" "*(MAX_SPEC_BYTES+1))
        self.assertEqual(self.run_cli().returncode,2)


if __name__=="__main__":
    unittest.main()
