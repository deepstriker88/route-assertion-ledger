import json
import tempfile
import unittest
from pathlib import Path

from route_assertion_ledger import desktop, audit, InvalidInput
from route_assertion_ledger.desktop_ui import write_new_json


class DesktopAdapterTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.spec,self.records,self.policy=desktop.demo_data()

    def files(self,records=None,mode="JSON"):
        s=self.root/"spec.json";s.write_text(json.dumps(self.spec))
        r=self.root/"records.json";records=self.records if records is None else records
        r.write_text(json.dumps(records) if mode=="JSON" else "".join(json.dumps(x)+"\n" for x in records))
        p=self.root/"policy.json";p.write_text(json.dumps(self.policy))
        return {"spec":s,"evidence":r,"format":mode,"policy":p,"pin":""}

    def test_real_example_and_core_parity(self):
        r=desktop.demo()
        self.assertEqual(r.state,"review")
        self.assertEqual(r.data,audit(self.spec,self.records,self.policy))
        self.assertEqual(r.metrics[0],("Covered","1/2"))
        self.assertIn("missing 404",r.details[0])

    def test_valid_json_and_jsonl(self):
        records=[{**x,"asserted":True} for x in self.records]
        for mode in ("JSON","JSONL"):
            r=desktop.run(self.files(records,mode))
            self.assertEqual(r.state,"pass")
            self.assertEqual(r.data,audit(self.spec,records,self.policy))

    def test_pin_mismatch_is_review(self):
        values=self.files([{**x,"asserted":True} for x in self.records])
        good=desktop.run(values)
        values["pin"]=good.data["scope_sha256"]
        self.assertEqual(desktop.run(values).state,"pass")
        values["pin"]="f"*64
        self.assertEqual(desktop.run(values).state,"review")

    def test_invalid_evidence_not_a_pass(self):
        values=self.files()
        values["evidence"].write_text("not JSON")
        with self.assertRaises(InvalidInput):desktop.run(values)

    def test_no_raw_unknown_operation_echo(self):
        values=self.files(self.records+[{"operation":"GET https://private.invalid/secret","status":200,"asserted":True}])
        r=desktop.run(values)
        self.assertEqual(r.state,"review")
        self.assertNotIn("private.invalid",json.dumps(r.data))

    def test_preflight_mode_and_synthetic_example(self):
        sample={"openapi":"3.1.0","paths":{"/a":{"get":{"operationId":"private-id"}}}}
        first=self.root/"first.json";first.write_text(json.dumps(sample))
        second=self.root/"second.json";second.write_text(json.dumps(sample))
        r=desktop.run({"mode":"Spec preflight","specs":(first,second),"evidence":"/not/read"})
        self.assertEqual(r.state,"review")
        self.assertEqual(r.data["duplicate_id_groups"],1)
        self.assertEqual(r.metrics[0],("Documents",2))
        self.assertNotIn("private-id",json.dumps(r.data))
        self.assertEqual(desktop.required_for_mode({"mode":"Spec preflight"}),("specs",))
        self.assertEqual(desktop.visible_for_mode({"mode":"Spec preflight"}),("mode","specs"))
        self.assertEqual(desktop.demo_for_mode({"mode":"Spec preflight"}).state,"review")
        with self.assertRaises(InvalidInput):desktop.run({"mode":"Spec preflight","specs":(first,)*9})

    def test_export_new_file_only(self):
        p=self.root/"report.json";r=desktop.demo().data
        write_new_json(p,r)
        self.assertEqual(json.loads(p.read_bytes()),r)
        with self.assertRaises(FileExistsError):write_new_json(p,{})
