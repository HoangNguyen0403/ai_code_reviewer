from typing import Tuple

import aiohttp

from .base import PullRequestClient


class AzureDevOpsClient(PullRequestClient):
    """
    Azure DevOps API Client implementing the PullRequestClient interface.
    """

    def __init__(
        self, org_url: str, project: str, repo_id: str, pat: str, platform: str
    ):
        super().__init__(org_url, project, repo_id, pat, platform)
        self.headers = {"Authorization": f"Basic {self._base64_pat()}"}
        self._api_version = "7.1"
        self._comment_api_version = "7.1-preview.1"

    def _base64_pat(self) -> str:
        return self._base64_encode(f":{self.auth_token}")

    async def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str]:
        url = f"{self.org_url}/{self.project}/_apis/git/repositories/{self.repo_id}/pullRequests/{pr_id}?api-version={self._api_version}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Failed to get PR details: {resp.status} {await resp.text()}"
                    )
                data = await resp.json()
                return (
                    data["title"],
                    data["description"],
                    data["sourceRefName"],
                    data["targetRefName"],
                )

    async def get_pr_diff(self, pr_id: str) -> str:
        url = f"{self.org_url}/{self.project}/_apis/git/repositories/{self.repo_id}/pullRequests/{pr_id}/diffs?api-version={self._api_version}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Failed to get PR diff: {resp.status} {await resp.text()}"
                    )
                return await resp.text()

    async def post_comment(self, pr_id, file_path, line, message):
        url = f"https://dev.azure.com/{self.org_url}/{self.project}/_apis/git/repositories/{self.repo_id}/pullRequests/{pr_id}/threads?api-version=7.1-preview.1"
        headers = {
            "Authorization": f"Basic {self.auth_token}",
            "Content-Type": "application/json",
        }
        data = {
            "comments": [{"parentCommentId": 0, "content": message, "commentType": 1}],
            "status": 1,
            "threadContext": {
                "filePath": f"/{file_path}",
                "rightFileStart": {"line": line, "offset": 1},
                "rightFileEnd": {"line": line, "offset": 1},
            },
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status not in (200, 201):
                    raise RuntimeError(
                        f"Failed to post comment: {resp.status} {await resp.text()}"
                    )
                return await resp.json()
