from typing import Dict, List, Tuple, Optional

import aiohttp

from .base import PullRequestClient


class GitHubClient(PullRequestClient):
    def __init__(
        self, org_url: str, project: str, repo_id: str, auth_token: str, platform: str
    ):
        super().__init__(org_url, project, repo_id, auth_token, platform)
        self.headers = {"Authorization": f"Bearer {self.auth_token}"}
        # Use owner (project) + repo name for GitHub REST endpoints
        self.repo_full_name = f"{self.project}/{self.repo_id}"

    async def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str, str, str]:
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
                return (
                    pr["title"],
                    pr.get("body") or "",
                    pr["head"]["ref"],
                    pr["base"]["ref"],
                    pr["head"]["sha"],
                    pr["base"]["sha"],
                )

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

    async def post_comment(self, pr_id: str, comment: Dict):
        url = f"https://api.github.com/repos/{self.repo_full_name}/pulls/{pr_id}/comments"
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Accept": "application/vnd.github+json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=comment) as resp:
                if resp.status not in (200, 201):
                    raise RuntimeError(
                        f"Failed to post comment: {resp.status} {await resp.text()}"
                    )
                return await resp.json()

    async def post_comments_batch(self, pr_id: str, comments: List[Dict]) -> bool:
        # Update-in-place or create individual comments to support multiline reliably
        existing_map = await self._get_existing_markers_map(pr_id)
        success = True
        for c in comments:
            marker = self._extract_marker(c.get("body", ""))
            if marker and marker in existing_map:
                comment_id, old_body = existing_map[marker]
                if old_body != c.get("body", ""):
                    try:
                        await self._update_review_comment(comment_id, c.get("body", ""))
                        existing_map[marker] = (comment_id, c.get("body", ""))
                    except Exception:
                        success = False
                # else: unchanged, skip
            else:
                try:
                    response = await self.post_comment(pr_id, c)
                    if marker:
                        existing_map[marker] = (
                            response.get("id"),
                            c.get("body", ""),
                        )
                except Exception:
                    success = False
        return success

    async def _get_existing_markers_map(self, pr_id: str) -> Dict[str, tuple]:
        marker_prefix = "<!-- ai-pr-reviewer:"
        url = f"https://api.github.com/repos/{self.repo_full_name}/pulls/{pr_id}/comments?per_page=100"
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Accept": "application/vnd.github+json",
        }
        existing: Dict[str, tuple] = {}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for c in data:
                        body = c.get("body", "")
                        if marker_prefix in body:
                            try:
                                start = body.index(marker_prefix) + len(marker_prefix)
                                end = body.index("-->", start)
                                marker = body[start:end].strip()
                                existing[marker] = (c.get("id"), body)
                            except Exception:
                                continue
        return existing

    def _extract_marker(self, body: str) -> Optional[str]:
        marker_prefix = "<!-- ai-pr-reviewer:"
        if marker_prefix in body:
            try:
                start = body.index(marker_prefix) + len(marker_prefix)
                end = body.index("-->", start)
                return body[start:end].strip()
            except Exception:
                return None
        return None

    async def _update_review_comment(self, comment_id: int, new_body: str) -> Dict:
        url = f"https://api.github.com/repos/{self.repo_full_name}/pulls/comments/{comment_id}"
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Accept": "application/vnd.github+json",
        }
        payload = {"body": new_body}
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status not in (200):
                    raise RuntimeError(
                        f"Failed to update comment {comment_id}: {resp.status} {await resp.text()}"
                    )
                return await resp.json()

    async def post_summary_comment(self, pr_id: str, body: str) -> dict:
        # Use issue comments for summary; update-in-place via marker
        marker_prefix = "<!-- ai-pr-reviewer:summary:"
        list_url = f"https://api.github.com/repos/{self.repo_full_name}/issues/{pr_id}/comments?per_page=100"
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Accept": "application/vnd.github+json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(list_url, headers=headers) as lresp:
                if lresp.status == 200:
                    items = await lresp.json()
                    for c in items:
                        b = c.get("body", "")
                        if marker_prefix in b:
                            # Update
                            cid = c.get("id")
                            upd_url = f"https://api.github.com/repos/{self.repo_full_name}/issues/comments/{cid}"
                            async with session.patch(upd_url, headers=headers, json={"body": body}) as uresp:
                                uresp.raise_for_status()
                                return await uresp.json()
        # Create new
        create_url = f"https://api.github.com/repos/{self.repo_full_name}/issues/{pr_id}/comments"
        async with aiohttp.ClientSession() as session:
            async with session.post(create_url, headers=headers, json={"body": body}) as cresp:
                cresp.raise_for_status()
                return await cresp.json()

    def format_comment_payload(
        self,
        old_file_path: str,
        new_file_path: str,
        line: int,
        message: str,
        head_sha: str,
        base_sha: str,
        end_line: int = None,
        diff_position: Optional[int] = None,
        start_diff_position: Optional[int] = None,
        end_diff_position: Optional[int] = None,
    ) -> dict:
        payload = {
            "body": message,
            "commit_id": head_sha,
            "path": new_file_path or old_file_path,
            "side": "RIGHT",
        }
        if end_line and end_line != line:
            payload.update(
                {
                    "start_commit_id": base_sha,
                    "start_line": line,
                    "line": end_line,
                    "start_side": "RIGHT",
                    "side": "RIGHT",
                }
            )
            if start_diff_position:
                payload["start_position"] = start_diff_position
            if end_diff_position:
                payload["position"] = end_diff_position
            elif diff_position:
                payload["position"] = diff_position
        else:
            payload["line"] = line
            if diff_position:
                payload["position"] = diff_position
        return payload
