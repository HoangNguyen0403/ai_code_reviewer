from typing import Dict, List, Tuple, Optional

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

    async def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str, str, str]:
        url = f"{self.org_url}/{self.project}/_apis/git/repositories/{self.repo_id}/pullRequests/{pr_id}?api-version={self._api_version}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Failed to get PR details: {resp.status} {await resp.text()}"
                    )
                data = await resp.json()
                return (
                    data.get("title", ""),
                    data.get("description", ""),
                    data.get("sourceRefName", ""),
                    data.get("targetRefName", ""),
                    data.get("lastMergeSourceCommit", {}).get("commitId", ""),
                    data.get("lastMergeTargetCommit", {}).get("commitId", ""),
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

    async def post_comment(self, pr_id: str, comment: Dict):
        url = f"{self.org_url}/{self.project}/_apis/git/repositories/{self.repo_id}/pullRequests/{pr_id}/threads?api-version={self._comment_api_version}"
        headers = {
            "Authorization": f"Basic {self._base64_pat()}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=comment) as resp:
                if resp.status not in (200, 201):
                    raise RuntimeError(
                        f"Failed to post comment: {resp.status} {await resp.text()}"
                    )
                return await resp.json()

    async def post_comments_batch(self, pr_id: str, comments: List[Dict]) -> bool:
        success = True
        existing_markers = await self._get_existing_markers_map(pr_id)

        for payload in comments:
            message = (
                payload.get("comments", [{}])[0].get("content", "")
                if payload.get("comments")
                else ""
            )
            marker = self._extract_marker(message)

            try:
                if marker and marker.startswith("summary:"):
                    marker = None

                if marker and marker in existing_markers:
                    thread_id, comment_id, old_content, thread_ctx = existing_markers[
                        marker
                    ]
                    if old_content != message:
                        await self._update_comment(
                            pr_id, thread_id, comment_id, message
                        )
                        existing_markers[marker] = (
                            thread_id,
                            comment_id,
                            message,
                            thread_ctx,
                        )
                else:
                    response = await self.post_comment(pr_id, payload)
                    if marker:
                        try:
                            thread_id = response.get("id")
                            comments_resp = response.get("comments", [])
                            comment_id = (
                                comments_resp[0].get("id") if comments_resp else None
                            )
                            thread_ctx = response.get("threadContext")
                            if thread_id and comment_id:
                                existing_markers[marker] = (
                                    thread_id,
                                    comment_id,
                                    message,
                                    thread_ctx,
                                )
                        except Exception:
                            pass
            except Exception:
                success = False

        return success

    async def post_summary_comment(self, pr_id: str, body: str) -> dict:
        existing_markers = await self._get_existing_markers_map(pr_id)
        summary_entry = None
        for marker, value in existing_markers.items():
            if marker.startswith("summary:"):
                summary_entry = value
                break

        if summary_entry:
            thread_id, comment_id, current_body, _ = summary_entry
            if current_body != body:
                await self._update_comment(pr_id, thread_id, comment_id, body)
            return {
                "threadId": thread_id,
                "commentId": comment_id,
                "status": "updated",
            }

        payload = {
            "comments": [
                {"parentCommentId": 0, "content": body, "commentType": 1}
            ],
            "status": 1,
        }
        return await self.post_comment(pr_id, payload)

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
        path = f"/{new_file_path or old_file_path}"
        thread_context = {
            "filePath": path,
            "rightFileStart": {"line": line, "offset": 1},
            "rightFileEnd": {"line": end_line or line, "offset": 1},
        }
        return {
            "comments": [
                {"parentCommentId": 0, "content": message, "commentType": 1}
            ],
            "status": 1,
            "threadContext": thread_context,
        }

    async def _get_existing_markers_map(self, pr_id: str) -> Dict[str, tuple]:
        marker_prefix = "<!-- ai-pr-reviewer:"
        list_url = f"{self.org_url}/{self.project}/_apis/git/repositories/{self.repo_id}/pullRequests/{pr_id}/threads?api-version={self._comment_api_version}"
        headers = {
            "Authorization": f"Basic {self._base64_pat()}",
            "Content-Type": "application/json",
        }
        existing: Dict[str, tuple] = {}
        async with aiohttp.ClientSession() as session:
            async with session.get(list_url, headers=headers) as resp:
                if resp.status != 200:
                    return existing
                data = await resp.json()
                for thread in data.get("value", []):
                    thread_id = thread.get("id")
                    thread_ctx = thread.get("threadContext")
                    for comment in thread.get("comments", []):
                        content = comment.get("content", "")
                        marker = self._extract_marker(content)
                        if marker:
                            existing[marker] = (
                                thread_id,
                                comment.get("id"),
                                content,
                                thread_ctx,
                            )
        return existing

    def _extract_marker(self, body: str) -> Optional[str]:
        marker_prefix = "<!-- ai-pr-reviewer:"
        if marker_prefix in body:
            try:
                start = body.index(marker_prefix) + len(marker_prefix)
                end = body.index("-->", start)
                return body[start:end].strip()
            except ValueError:
                return None
        return None

    async def _update_comment(
        self, pr_id: str, thread_id: int, comment_id: int, body: str
    ) -> None:
        url = f"{self.org_url}/{self.project}/_apis/git/repositories/{self.repo_id}/pullRequests/{pr_id}/threads/{thread_id}/comments/{comment_id}?api-version={self._comment_api_version}"
        headers = {
            "Authorization": f"Basic {self._base64_pat()}",
            "Content-Type": "application/json",
        }
        payload = {"content": body, "commentType": 1}
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status >= 400:
                    raise RuntimeError(
                        f"Failed to update comment {comment_id}: {resp.status} {await resp.text()}"
                    )
