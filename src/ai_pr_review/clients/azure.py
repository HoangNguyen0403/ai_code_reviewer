from typing import Tuple

import requests

from .base import PullRequestClient  # Import the base class


class AzureDevOpsClient(PullRequestClient):
    """
    Azure DevOps API Client implementing the PullRequestClient interface.
    """

    def __init__(self, org_url: str, project: str, repo_id: str, pat: str):
        # Use auth_token for PAT in the base class
        super().__init__(org_url, project, repo_id, pat)
        self.headers = {"Authorization": f"Basic {self._base64_pat()}"}
        self._api_version = "7.1"  # Use a constant for API version
        self._comment_api_version = (
            "7.1-preview.1"  # Use a constant for comment API version
        )

    def _base64_pat(self) -> str:
        # Use the helper from the base class
        return self._base64_encode(f":{self.auth_token}")

    def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str]:
        url = f"{self.org_url}/{self.project}/_apis/git/repositories/{self.repo_id}/pullRequests/{pr_id}?api-version={self._api_version}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        return (
            data["title"],
            data["description"],
            data["sourceRefName"],
            data["targetRefName"],
        )

    def get_pr_diff(self, pr_id: str) -> str:
        url = f"{self.org_url}/{self.project}/_apis/git/repositories/{self.repo_id}/pullRequests/{pr_id}/diffs?api-version={self._api_version}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.text

    def post_comment(self, pr_id: str, thread_id: int, content: str):
        url = f"{self.org_url}/{self.project}/_apis/git/repositories/{self.repo_id}/pullRequests/{pr_id}/threads/{thread_id}/comments?api-version={self._comment_api_version}"
        payload = {"parentCommentId": 0, "content": content, "commentType": 1}
        resp = requests.post(
            url,
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# Remove environment loading, orchestrator, and main entry point from this file
# These will be handled in main.py and potentially a new config module.
