import os
import yaml
import requests
import re
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class GitHubClient:
    def __init__(self, repo_owner, repo_name, github_token):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.github_token = github_token

    def get_open_pull_requests(self):
        logging.info("Fetching open pull requests.")
        url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/pulls"
        headers = {"Authorization": f"token {self.github_token}"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        prs = response.json()
        logging.info(f"Found {len(prs)} open pull request(s).")
        return prs

    def list_repo_files(self, path=""):
        logging.info(f"Listing repository files recursively in path '{path}'.")
        files = []
        url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/contents/{path}"
        headers = {"Authorization": f"token {self.github_token}"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        items = response.json()
        for item in items:
            if item["type"] == "file":
                files.append(item)
            elif item["type"] == "dir":
                # Recursively list files in subfolders.
                sub_files = self.list_repo_files(item["path"])
                files.extend(sub_files)
        logging.info(f"Total files found in '{path}': {len(files)}")
        return files

    def get_file_content(self, file_info):
        # Prefer "raw_url" if available; otherwise, use "download_url".
        download_url = file_info.get("raw_url") or file_info.get("download_url")
        if not download_url:
            logging.warning(f"No URL found for file: {file_info.get('filename') or file_info.get('name')}")
            return ""
        logging.info(f"Downloading content for file: {file_info.get('filename') or file_info.get('name')}")
        response = requests.get(download_url)
        response.raise_for_status()
        return response.text

    def get_file_by_path(self, path):
        logging.info(f"Fetching file by path: {path}")
        url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/contents/{path}"
        headers = {"Authorization": f"token {self.github_token}"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    def get_pr_files(self, pr_number):
        logging.info(f"Fetching files for PR #{pr_number}")
        url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/pulls/{pr_number}/files"
        headers = {"Authorization": f"token {self.github_token}"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        files = response.json()
        logging.info(f"Found {len(files)} file(s) in PR #{pr_number}.")
        return files


class AnalysisEngine:
    def __init__(self, llm_server_url, model):
        self.llm_server_url = llm_server_url.rstrip('/')
        self.model = model

    def construct_prompt(self, reports):
        prompt = (
            "You are a project health evaluation expert. Analyze the following "
            "project reports to determine the overall health of the project. Retain all important attributes such as maintenance history, contributor activity, trends, and risks.\n\n"
            "Below are the reports:\n\n"
        )
        for idx, report in enumerate(reports, 1):
            prompt += f"Report {idx}:\n{report}\n\n"
        prompt += "Please summarize your evaluation and provide actionable recommendations."
        logging.info("Constructed detailed final prompt for LLM.")
        return prompt

    def analyze_reports(self, reports):
        # Use the aggregated individual analyses to create a final summary.
        aggregated = "\n\n".join(reports)
        final_prompt = (
            "Based on the following individual analysis steps, produce a comprehensive evaluation summary "
            "with your detailed chain-of-thought. Retain all crucial attributes and include your reasoning process:\n\n"
            f"{aggregated}\n\nFinal Summary:"
        )
        payload = {
            "model": self.model,
            "prompt": final_prompt,
            "max_tokens": 250,
            "temperature": 0,
            "stop": ["\n"],
            "stream": False
        }
        logging.info("Sending aggregated prompt to Ollama LLM API for final summary.")
        url = f"{self.llm_server_url}/api/generate"
        logging.info(f"Constructed URL for final analysis: {url}")
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logging.info("Received final summary from LLM.")
        return response.json().get("response", "").strip()

    def analyze_single_report(self, report, index):
        # For each report (file content) ask the LLM to provide a detailed analysis including its chain-of-thought.
        prompt = (
            f"Analyze the following report (file {index}) and provide your thinking process step by step. "
            "Make sure to retain all important attributes (e.g. maintenance, trends, risks, contributor details) "
            "from the report. Report:\n\n"
            f"{report}\n\n"
            "Your detailed analysis (chain-of-thought):"
        )
        payload = {
            "model": self.model,
            "prompt": prompt,
            "max_tokens": 150,
            "temperature": 0,
            "stop": ["\n"],
            "stream": False
        }
        url = f"{self.llm_server_url}/api/generate"
        logging.info(f"Sending single report payload to LLM API for file {index}: {payload}")
        response = requests.post(url, json=payload)
        response.raise_for_status()
        thought = response.json().get("response", "").strip()
        logging.info(f"Received analysis for file {index}:\n{thought}")
        return thought


class ReportExtractor:
    def extract_project_name_from_pr(self, pr, llm_engine=None):
        title = pr.get("title", "")
        match = re.match(r"([\w\-]+)[\s:]+", title)
        candidate = match.group(1) if match else None
        if candidate and candidate.lower() != "create":
            logging.info(f"Extracted project name '{candidate}' from PR title.")
            return candidate
        body = pr.get("body", "")
        match_body = re.search(r"project\s*name\s*[:\-]\s*([\w\-]+)", body, re.IGNORECASE)
        candidate_body = match_body.group(1) if match_body else None
        if candidate_body and candidate_body.lower() != "create":
            logging.info(f"Extracted project name '{candidate_body}' from PR body.")
            return candidate_body
        if llm_engine:
            inferred = llm_engine.infer_project_name(title, body)
            return inferred
        logging.warning("Failed to extract project name from PR using heuristics.")
        return None

    def list_possible_projects(self, github_client):
        try:
            file_info = github_client.get_file_by_path("tac/project-updates/2025/2025-schedule.md")
            content = github_client.get_file_content(file_info)
            projects = set()
            if "Project" in content and "|" in content:
                lines = content.splitlines()
                header_found = False
                header_cols = []
                for line in lines:
                    if not header_found and '|' in line:
                        header_cols = [col.strip().lower() for col in line.strip("|").split("|")]
                        if "project" in header_cols:
                            header_found = True
                        continue
                    if header_found:
                        if re.match(r"^\s*[-|]+\s*$", line):
                            continue
                        if '|' in line:
                            cols = [col.strip() for col in line.strip("|").split("|")]
                            if header_cols and len(cols) == len(header_cols):
                                idx = header_cols.index("project")
                                project_name = cols[idx].strip()
                                if project_name and not re.match(r'^[\-\s]+$', project_name):
                                    projects.add(project_name.lower())
                project_list = list(projects)
                logging.info(f"Projects extracted from schedule table: {project_list}")
                return project_list
            else:
                raise ValueError("Schedule file does not appear to contain a markdown table.")
        except Exception as e:
            logging.warning(f"Failed to extract projects from schedule file: {e}")
            files = github_client.list_repo_files()
            candidate_projects = set()
            for file_info in files:
                if file_info["type"] != "file":
                    continue
                name = file_info.get("name", "")
                tokens = re.split(r'\W+', name)
                for token in tokens:
                    if token and len(token) > 2:
                        candidate_projects.add(token.lower())
            candidate_list = list(candidate_projects)
            logging.info(f"Possible projects from file names: {candidate_list}")
            return candidate_list

    def determine_project_for_pr(self, pr, candidate_projects, github_client, llm_engine=None):
        pr_text = f"{pr.get('title', '')} {pr.get('body', '')} {pr.get('description', '')}".lower()
        logging.info("Attempting to correlate PR with known project names.")
        for project in candidate_projects:
            if project in pr_text:
                logging.info(f"Determined project '{project}' from PR text correlation.")
                return project
        logging.warning("Unable to determine project from PR text correlation.")
        return None

    def filter_reports(self, files, project_name):
        if not project_name:
            return []
        project_pattern = re.compile(re.escape(project_name), re.IGNORECASE)
        filtered = [f for f in files if f["type"] == "file" and project_pattern.search(f["name"])]
        logging.info(f"Filtered {len(filtered)} files matching project '{project_name}'.")
        return filtered

    def extract_reports_from_repo(self, github_client, project_name):
        files = github_client.list_repo_files()
        matching_files = self.filter_reports(files, project_name)
        reports = []
        for file_info in matching_files:
            content = github_client.get_file_content(file_info)
            if project_name.lower() in content.lower():
                reports.append(content)
                logging.info(f"Added report from file '{file_info.get('name')}'.")
        return reports

    def extract_reports_from_pr(self, pr, github_client):
        reports = []
        if "number" in pr:
            pr_files = github_client.get_pr_files(pr["number"])
            for file_info in pr_files:
                logging.info(f"Extracting report from PR files '{file_info}'.")
                content = github_client.get_file_content(file_info)
                if content:
                    reports.append(content)
            if reports:
                logging.info("Extracted report from PR files.")
                return reports
        content = f"{pr.get('body', '')}\n{pr.get('description', '')}".strip()
        if content:
            logging.info("Extracted report from PR text.")
            return [content]
        logging.warning("No report found in PR content.")
        return []


class ResultManager:
    def __init__(self, output_file):
        self.output_file = output_file

    def write_output(self, project, content):
        # Override the output file with the new contents (chain-of-thought update)
        with open(self.output_file, "w") as f:
            f.write(f"{project}:\n\n{content}\n")
        logging.info(f"Overwritten results for project '{project}' in '{self.output_file}'.")


class AIAgent:
    def __init__(self, config):
        self.config = config
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            raise ValueError("GITHUB_TOKEN environment variable is not set.")
        self.github_client = GitHubClient(
            config["github"]["repo_owner"],
            config["github"]["repo_name"],
            github_token
        )
        self.analysis_engine = AnalysisEngine(
            config["llm"]["server_url"],
            config["llm"]["model"]
        )
        self.report_extractor = ReportExtractor()
        self.result_manager = ResultManager(config["output"]["result_file"])

    def process_pull_request(self, pr, candidate_projects):
        project = self.report_extractor.determine_project_for_pr(
            pr, candidate_projects, self.github_client, self.analysis_engine
        )
        if not project:
            logging.error("Skipping PR; unable to determine project.")
            return

        # Extract reports from PR and repository
        reports = []
        reports.extend(self.report_extractor.extract_reports_from_pr(pr, self.github_client))
        reports.extend(self.report_extractor.extract_reports_from_repo(self.github_client, project))

        if reports:
            # Iteratively analyze each report file
            analysis_steps = []
            for idx, report in enumerate(reports, 1):
                step = self.analysis_engine.analyze_single_report(report, idx)
                analysis_steps.append(f"Step {idx} Analysis:\n{step}")
                # Write each step to the output file
                self.result_manager.write_output(project, "\n\n".join(analysis_steps))
            # Obtain final summary based on individual analysis steps
            final_summary = self.analysis_engine.analyze_reports(analysis_steps)
            self.result_manager.write_output(project, f"Final Summary:\n{final_summary}")
            logging.info(f"Final results for project '{project}' processed.")
        else:
            logging.warning(f"No reports found for project '{project}'.")

    def run(self):
        candidate_projects = self.report_extractor.list_possible_projects(self.github_client)
        pull_requests = self.github_client.get_open_pull_requests()
        if not pull_requests:
            logging.info("No open pull requests found.")
            return

        for pr in pull_requests:
            self.process_pull_request(pr, candidate_projects)


def load_config(config_path="agent_config.yaml"):
    logging.info(f"Loading configuration from {config_path}.")
    with open(config_path, "r") as file:
        return yaml.safe_load(file)


if __name__ == "__main__":
    config = load_config()
    agent = AIAgent(config)
    agent.run()
