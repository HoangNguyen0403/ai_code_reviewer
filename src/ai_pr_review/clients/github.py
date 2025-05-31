from typing import Tuple

import requests
from github import Github

from .base import PullRequestClient


class GitHubClient(PullRequestClient):
    def __init__(self, org_url: str, project: str, repo_id: str, auth_token: str):
        super().__init__(org_url, project, repo_id, auth_token)
        self.headers = {"Authorization": f"Bearer {self.auth_token}"}
        self.repo_full_name = (
            f"{self.org_url}/{self.repo_id}" if self.org_url else self.repo_id
        )

    def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str]:
        gh = Github(self.auth_token)
        repo_obj = gh.get_repo(self.repo_full_name)
        pr = repo_obj.get_pull(int(pr_id))
        return pr.title, pr.body, pr.head.ref, pr.base.ref

    def get_pr_diff(self, pr_id: str) -> str:
        api_url = (
            f"https://api.github.com/repos/{self.repo_full_name}/pulls/{pr_id}.diff"
        )
        headers = self.headers.copy()
        headers["Accept"] = "application/vnd.github.v3.diff"
        response = requests.get(api_url, headers=headers)
        if response.status_code == 200:
            return response.text
        else:
            raise RuntimeError(
                f"Failed to get diff: {response.status_code} {response.text}"
            )

    def post_comment(self, pr_id: str, thread_id: int, content: str) -> dict:
        gh = Github(self.auth_token)
        repo_obj = gh.get_repo(self.repo_full_name)
        pr = repo_obj.get_pull(int(pr_id))
        # GitHub does not use thread_id for PR review comments; just post to the PR
        comment = pr.create_issue_comment(content)
        return {"status": "success", "comment_id": comment.id}
