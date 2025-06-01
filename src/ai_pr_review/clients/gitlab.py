from typing import Tuple

import aiohttp

from .base import PullRequestClient


class GitLabClient(PullRequestClient):
    def __init__(
        self, org_url: str, project: str, repo_id: str, auth_token: str, platform: str
    ):
        super().__init__(org_url, project, repo_id, auth_token, platform)
        self.headers = {"PRIVATE-TOKEN": self.auth_token}
        self.api_base = org_url.rstrip("/")
        self.project_id = repo_id  # Numeric project ID for GitLab

    async def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str, str]:
        pr_url = (
            f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}"
        )
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(pr_url) as resp:
                resp.raise_for_status()
                pr_data = await resp.json()
                print(f"PR Detail {pr_data}")
                return (
                    pr_data["title"],
                    pr_data["description"],
                    pr_data["source_branch"],
                    pr_data["target_branch"],
                    pr_data["diff_refs"]["head_sha"],
                )

    async def get_pr_diff(self, pr_id: str) -> str:
        diff_url = f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}/changes"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(diff_url) as resp:
                resp.raise_for_status()
                diff_data = await resp.json()
                diffs = []
                for change in diff_data.get("changes", []):
                    diffs.append(
                        f"diff --git a/{change['old_path']} b/{change['new_path']}\n{change['diff']}"
                    )
                return "\n".join(diffs)

    async def post_comment(self, pr_id, body, position):
        url = f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}/discussions"
        data = {
            "body": body,
            "position": position,
        }
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(url, json=data) as response:
                response.raise_for_status()
                return await response.json()

    def format_comment_payload(
        self, file_path: str, line: int, message: str, head_sha: str
    ) -> dict:
        return {
            "body": message,
            "position": {
                "position_type": "text",
                "new_path": file_path,
                "new_line": line,
                "head_sha": head_sha,
            },
        }
