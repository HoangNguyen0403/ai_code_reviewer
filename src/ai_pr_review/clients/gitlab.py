from typing import Tuple

import requests

from .base import PullRequestClient


class GitLabClient(PullRequestClient):
    def __init__(self, org_url: str, project: str, repo_id: str, auth_token: str):
        super().__init__(org_url, project, repo_id, auth_token)
        self.headers = {"PRIVATE-TOKEN": self.auth_token}
        self.api_base = org_url.rstrip("/")
        self.project_id = repo_id  # Numeric project ID for GitLab

    def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str]:
        pr_url = (
            f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}"
        )
        resp = requests.get(pr_url, headers=self.headers)
        resp.raise_for_status()
        pr_data = resp.json()
        return (
            pr_data["title"],
            pr_data["description"],
            pr_data["source_branch"],
            pr_data["target_branch"],
        )

    def get_pr_diff(self, pr_id: str) -> str:
        diff_url = f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}/changes"
        resp = requests.get(diff_url, headers=self.headers)
        resp.raise_for_status()
        diff_data = resp.json()
        diffs = []
        for change in diff_data.get("changes", []):
            diffs.append(
                f"diff --git a/{change['old_path']} b/{change['new_path']}\n{change['diff']}"
            )
        return "\n".join(diffs)

    def post_comment(self, pr_id: str, thread_id: int, content: str) -> dict:
        # GitLab API for posting a note to a merge request
        notes_url = f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}/notes"
        data = {"body": content}
        resp = requests.post(notes_url, headers=self.headers, json=data)
        resp.raise_for_status()
        note = resp.json()
        return {"status": "success", "note_id": note["id"]}
