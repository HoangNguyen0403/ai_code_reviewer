from typing import Tuple

import aiohttp

from .base import PullRequestClient


class GitHubClient(PullRequestClient):
    def __init__(self, org_url: str, project: str, repo_id: str, auth_token: str):
        super().__init__(org_url, project, repo_id, auth_token)
        self.headers = {"Authorization": f"Bearer {self.auth_token}"}
        self.repo_full_name = (
            f"{self.org_url}/{self.repo_id}" if self.org_url else self.repo_id
        )

    async def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str]:
        # Direct HTTP call since PyGithub is not async
        api_url = f"https://api.github.com/repos/{self.repo_full_name}/pulls/{pr_id}"
        headers = self.headers.copy()
        headers["Accept"] = "application/vnd.github+json"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Failed to get PR details: {resp.status} {await resp.text()}"
                    )
                pr = await resp.json()
                return pr["title"], pr["body"], pr["head"]["ref"], pr["base"]["ref"]

    async def get_pr_diff(self, pr_id: str) -> str:
        api_url = (
            f"https://api.github.com/repos/{self.repo_full_name}/pulls/{pr_id}.diff"
        )
        headers = self.headers.copy()
        headers["Accept"] = "application/vnd.github.v3.diff"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    raise RuntimeError(
                        f"Failed to get diff: {resp.status} {await resp.text()}"
                    )

    async def get_latest_commit_sha(self, pr_id: str) -> str:
        api_url = f"https://api.github.com/repos/{self.repo_full_name}/pulls/{pr_id}"
        headers = self.headers.copy()
        headers["Accept"] = "application/vnd.github+json"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Failed to get PR details: {resp.status} {await resp.text()}"
                    )
                pr = await resp.json()
                return pr["head"]["sha"]

    async def post_comment(self, pr_id, file_path, line, message):
        url = f"https://api.github.com/repos/{self.project}/{self.repo_id}/pulls/{pr_id}/comments"
        headers = {
            "Authorization": f"token {self.auth_token}",
            "Accept": "application/vnd.github+json",
        }
        last_commit_id = await self.get_latest_commit_sha(pr_id)
        data = {
            "body": message,
            "commit_id": last_commit_id,
            "path": file_path,
            "line": line,
            "side": "RIGHT",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status not in (200, 201):
                    raise RuntimeError(
                        f"Failed to post comment: {resp.status} {await resp.text()}"
                    )
                return await resp.json()
