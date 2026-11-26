import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from route_assertion_ledger import InvalidInput, load_json, MAX_SPEC_BYTES
from route_assertion_ledger.preflight import preflight


def spec(path="/items", id="listItems", **extra):
    return {"openapi":"3.1.0","paths":{path:{"get":{"operationId":id,"responses":{"200":{}}}}},**extra}


class SpecPreflightTests(unittest.TestCase):
    def test_cross_document_collision_external_ref_and_redaction(self):
        left=spec("/a", "PRIVATE_ID", components={"schemas":{"A":{"$ref":"https://private.invalid/secret"}}})
        right=spec("/b", "PRIVATE_ID", examples={"sample":{"$ref":"#/local"}})
        r=preflight([left,right])
        self.assertFalse(r["ok"])
        self.assertEqual(r["counts"],{"DUPLICATE_OPERATION_ID":2,"EXTERNAL_REF":1})
        self.assertEqual(r["duplicate_id_groups"],1)
        self.assertEqual(r["findings"][0]["pointer"],"/components/schemas/A/$ref")
        self.assertNotIn("private.invalid",json.dumps(r))
        self.assertNotIn("PRIVATE_ID",json.dumps(r))
        collisions=[x for x in r["findings"] if x["code"]=="DUPLICATE_OPERATION_ID"]
        self.assertEqual([x["document"] for x in collisions],[1,2])
        self.assertEqual(collisions[0]["pointer"],"/paths/~1a/get/operationId")

    def test_ref_ambiguous_and_unexpanded_path_item(self):
        r=preflight([{"swagger":"2.0","paths":{"/a":{"$ref":"#/somewhere"}},"examples":[{"$ref":""},{"$ref":42},{"$ref":"a b"},{"$ref":"#/ok"}]}])
        self.assertEqual(r["counts"],{"AMBIGUOUS_REF":3,"PATH_ITEM_REF_NOT_EXPANDED":1})
        self.assertEqual(r["inline_operations"],0)

    def test_clean_case_sensitive_ids_and_missing_ids(self):
        a=spec("/a","list");b=spec("/a","List")
        b["paths"]["/a"]["post"]={"responses":{"200":{}}}
        r=preflight([a,b])
        self.assertTrue(r["ok"])
        self.assertEqual(r["inline_operations"],3)

    def test_same_document_duplicates(self):
        a=spec("/a","same")
        a["paths"]["/b"]={"post":{"operationId":"same","responses":{"200":{}}}}
        self.assertEqual(preflight([a])["duplicate_id_groups"],1)

    def test_invalid_schema_inputs_and_duplicate_keys(self):
        for v in [[],[{"openapi":"3.2.0","paths":{}}],[{"openapi":"3.1.0"}],[spec()]*9]:
            with self.assertRaises(InvalidInput):preflight(v)
        with self.assertRaises(InvalidInput):load_json(b'{"openapi":"3.1.0","paths":{},"paths":{}}',MAX_SPEC_BYTES)

    def test_no_inline_operations_is_not_clean(self):
        self.assertEqual(preflight([{"openapi":"3.1.0","paths":{"/a":{"summary":"none"}}}])["counts"],{"NO_INLINE_OPERATIONS":1})
        self.assertEqual(preflight([{"openapi":"3.1.0","paths":{}}])["counts"],{"NO_INLINE_PATHS":1})

    def test_bounded_findings_and_invalid_ids(self):
        a=spec(id="")
        a["examples"]=[{"$ref":"other.json"} for _ in range(501)]
        r=preflight([a])
        self.assertTrue(r["truncated"])
        self.assertEqual(r["finding_count"],502)
        self.assertEqual(len(r["findings"]),500)
        self.assertEqual(r["counts"]["INVALID_OPERATION_ID"],1)

    def test_cli_exit_status_and_no_path_echo(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"private-filename.json"
            path.write_text(json.dumps(spec(components={"x":{"$ref":"file:///private/source.json"}})))
            cmd=[sys.executable,"-B","-m","route_assertion_ledger","--preflight",str(path)]
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(p.returncode,1,p.stderr)
            self.assertNotIn("private-filename",p.stdout)
            self.assertNotIn("/private/source",p.stdout)
            path.write_text(json.dumps(spec()))
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            path.write_text("bad")
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(p.returncode,2)
