import unittest
import re
from agent import ReportExtractor, AnalysisEngine

class TestReportExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = ReportExtractor()
        self.sample_pr_title = {
            "title": "Create 2025-annual-Hyperledger-FireFly.md",
            "body": "This PR contains the annual report. Project name: Hyperledger FireFly."
        }
        self.sample_pr_body = {
            "title": "",
            "body": "Project name: ProjectY. Quarterly metrics..."
        }

    def test_extract_project_name_from_pr_with_llm(self):
        # Simulate LLM response through a dummy engine.
        class DummyEngine:
            def infer_project_name(self, title, body):
                return "Hyperledger FireFly"
        dummy_engine = DummyEngine()
        project_name = self.extractor.extract_project_name_from_pr(self.sample_pr_title, dummy_engine)
        self.assertEqual(project_name, "Hyperledger FireFly")

    def test_list_possible_projects(self):
        # Test using a dummy GitHub client that returns a markdown table.
        class DummyClient:
            def list_repo_files(self, path=""):
                return []  # Not used when schedule file is present.
            def get_file_by_path(self, path):
                # Simulate a schedule file containing a markdown table.
                return {"download_url": "http://dummy-url/schedule.md"}
            def get_file_content(self, file_info):
                return (
                    "| Project | Status |\n"
                    "|---------|--------|\n"
                    "| Hyperledger FireFly | Active |\n"
                    "| ProjectY | Active |\n"
                    "| OpenProject | Inactive |"
                )
        dummy_client = DummyClient()
        projects = self.extractor.list_possible_projects(dummy_client)
        self.assertIn("hyperledger firefly", projects)
        self.assertIn("projecty", projects)
        self.assertIn("openproject", projects)

    def test_extract_reports_from_pr(self):
        reports = self.extractor.extract_reports_from_pr(self.sample_pr_title)
        self.assertEqual(reports, [self.sample_pr_title["body"]])


class TestAnalysisEngine(unittest.TestCase):
    def setUp(self):
        self.engine = AnalysisEngine("http://localhost:8000/analyze")
        self.sample_reports = ["Content of report 1", "Content of report 2"]

    def test_construct_prompt(self):
        prompt = self.engine.construct_prompt(self.sample_reports)
        self.assertIn("Report 1:", prompt)
        self.assertIn("Report 2:", prompt)

if __name__ == "__main__":
    unittest.main()