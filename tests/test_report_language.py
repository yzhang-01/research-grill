"""Check review completion, report languages, and the legacy ZIP contract."""

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "research-grill" / "scripts" / "grill.py"
YEAR, WEEK_NUMBER, _ = date.today().isocalendar()
WEEK = f"{YEAR}-W{WEEK_NUMBER:02d}"


class ReportLanguageTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="research-grill-tests-")
        self.addCleanup(self.scratch.cleanup)
        self.workspace = Path(self.scratch.name)

    def call(self, command, data=None, root=None, error=None):
        args = [sys.executable, "-B", str(SCRIPT), "--root", str(root or self.workspace),
                command, "--week", WEEK]
        if data is not None:
            args += ["--input", "-"]
        result = subprocess.run(args, input=json.dumps(data) if data is not None else "",
                                capture_output=True, encoding="utf-8", check=False)
        if error is not None:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(error, result.stderr)
            return
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def freeze(self, language=None, second_goal=False):
        self.call("init", {"project_id": "physics", "student_id": "participant-a",
                           "student_name": "Ana García · 刘"})
        plan = {"goals": [{"title": "Trace a result", "deliverable": "A source citation",
                            "criteria": "Provide a page and figure number", "due": date.today().isoformat()}]}
        if second_goal:
            plan["goals"].append({**plan["goals"][0], "title": "Check the baseline"})
        if language is not None:
            plan["language"] = language
        self.call("freeze", plan)

    def create_report(self, language=None):
        self.freeze(language)
        first = self.call("ask", {"kind": "goal", "goal_id": "G1", "prompt": "What did you deliver?"})
        self.call("answer", {"question_id": first["id"], "text": "Pas encore."})
        followup = self.call("ask", {"kind": "followup", "goal_id": "G1", "prompt": "What blocked the citation?"})
        self.call("answer", {"question_id": followup["id"], "text": "The appendix was unavailable."})
        final = self.call("ask", {"kind": "final"})
        self.call("answer", {"question_id": final["id"], "text": "No", "no_more": True})
        result = self.call("close", {"assessments": [
            {"goal_id": "G1", "status": "unfinished", "outcome": "No citation yet",
             "judgment": "insufficient", "basis": "No result cited",
             "response_observation": "Answered directly", "refs": [first["id"]]}
        ]})
        path = Path(result["path"])
        with zipfile.ZipFile(path) as archive:
            return path, json.loads(archive.read("record.json")), archive.read("report.md").decode("utf-8")

    def import_report(self, path):
        target = self.workspace / "reviewer"
        target.mkdir(exist_ok=True)
        result = self.call("import", {"paths": [str(path)]}, root=target)
        self.assertTrue(result["imported"][0]["added"])
        return self.call("view", {"project_id": "physics", "student_id": "participant-a"}, root=target)

    def test_english_default_exports_and_imports(self):
        path, record, report = self.create_report()
        self.assertIn("Review completed", report)
        self.assertIn("Progress (Unfinished)", report)
        self.assertEqual(record["language"], "en")
        self.assertEqual(record["questions"][-1]["prompt"], "Is there anything else you would like to add?")
        self.assertEqual(self.import_report(path)["questions"][0]["answer"], "Pas encore.")

    def test_chinese_exports_and_imports(self):
        path, record, report = self.create_report("zh-CN")
        self.assertIn("答辩已完成", report)
        self.assertEqual(record["questions"][-1]["prompt"], "你还有什么要补充的？")
        self.assertEqual(self.import_report(path)["language"], "zh-CN")

    def test_legacy_package_without_language_imports(self):
        _, record, report = self.create_report("zh-CN")
        del record["language"]
        del record["questions"][1]
        record["questions"][-1]["id"] = "Q2"
        path = self.workspace / "legacy-format.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("record.json", json.dumps(record, ensure_ascii=False))
            archive.writestr("report.md", report)
        imported = self.import_report(path)
        self.assertNotIn("language", imported)
        self.assertEqual(imported["questions"][0]["answer"], "Pas encore.")

    def test_final_requires_a_subsequent_answered_followup_for_each_goal(self):
        self.freeze(second_goal=True)
        followup = {"kind": "followup", "goal_id": "G1", "prompt": "Where did progress stop?"}
        self.call("ask", followup, error="answer the initial goal question")
        for goal in ("G1", "G2"):
            question = self.call("ask", {"kind": "goal", "goal_id": goal, "prompt": "What did you deliver?"})
            self.call("answer", {"question_id": question["id"], "text": "Nothing yet."})
        question = self.call("ask", {"kind": "followup", "prompt": "Anything blocking the project generally?"})
        self.call("answer", {"question_id": question["id"], "text": "No."})
        self.call("ask", {"kind": "final"}, error="follow-up first for: G1, G2")
        question = self.call("ask", followup)
        self.call("ask", {"kind": "final"}, error="answer the pending question first")
        self.call("answer", {"question_id": question["id"], "text": "I lost access to the paper."})
        self.call("ask", {"kind": "final"}, error="follow-up first for: G2")
        question = self.call("ask", {**followup, "goal_id": "G2"})
        self.call("answer", {"question_id": question["id"], "text": "I don't know."})
        self.assertEqual(self.call("ask", {"kind": "final"})["kind"], "final")
