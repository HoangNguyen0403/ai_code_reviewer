import traceback
from datetime import datetime
from typing import Dict, List, Tuple, Optional

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
        self._start_sha: Optional[str] = None

    async def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str, str, str]:
        pr_url = (
            f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}"
        )
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(pr_url) as resp:
                resp.raise_for_status()
                pr_data = await resp.json()
                print(f"PR Details: {pr_data}")
                diff_refs = pr_data.get("diff_refs", {})
                self._start_sha = diff_refs.get("start_sha")
                return (
                    pr_data.get("title", ""),
                    pr_data.get("description", ""),
                    pr_data.get("source_branch", ""),
                    pr_data.get("target_branch", ""),
                    diff_refs.get("head_sha", ""),
                    diff_refs.get("base_sha", ""),
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

    async def post_comment(self, pr_id: str, comment: Dict):
        url = f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}/discussions"
        body = comment.get("body", "")
        position = comment.get("position", {})
        data = {"body": body, "position": position}
        try:
            print(f"Posting comment on {url}: {data}")
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.post(url, json=data) as response:
                    if response.status >= 400:
                        error_text = await response.text()
                        raise Exception(
                            f"GitLab API error {response.status}: {error_text}"
                        )
                    response_data = await response.json()
                    return response_data
        except Exception as e:
            traceback.print_exc()
            return {"error": str(e)}

    async def post_comments_batch(self, pr_id: str, comments: List[Dict]) -> bool:
        """Submit multiple comments to the PR in a batch."""
        total_comments = len(comments)
        failed_comments = []
        success_count = 0

        print(f"Posting {total_comments} comments in batch")

        existing_markers = await self._get_existing_markers_map(pr_id)

        for idx, comment in enumerate(comments):
            body = comment.get("body", "")
            marker = self._extract_marker(body)

            try:
                if marker and marker.startswith("summary:"):
                    marker = None  # summary handled separately

                if marker and marker in existing_markers:
                    discussion_id, note_id, old_body = existing_markers[marker]
                    if old_body != body:
                        await self._update_discussion_note(
                            pr_id, discussion_id, note_id, body
                        )
                        existing_markers[marker] = (discussion_id, note_id, body)
                    success_count += 1
                else:
                    result = await self.post_comment(pr_id, comment)
                    if "error" in result:
                        raise Exception(result["error"])
                    if marker:
                        try:
                            disc_id = result.get("id")
                            notes = result.get("notes", [])
                            note_id = notes[0].get("id") if notes else None
                            if disc_id and note_id:
                                existing_markers[marker] = (disc_id, note_id, body)
                        except Exception:
                            pass
                    success_count += 1
            except Exception as exc:  # pragma: no cover - defensive
                error_msg = str(exc)
                print(
                    f"Failed to submit comment {idx + 1}/{total_comments}: {error_msg}"
                )
                position = comment.get("position", {})
                failed_comments.append(
                    {
                        "index": idx,
                        "comment": comment,
                        "error": error_msg,
                        "file_path": position.get("new_path"),
                        "line": position.get("new_line"),
                    }
                )

        print(
            f"Batch submission completed: {success_count}/{total_comments} comments processed"
        )

        if failed_comments:
            self._save_failed_gitlab_comments(pr_id, failed_comments)

        return success_count == total_comments

    async def post_summary_comment(self, pr_id: str, body: str) -> dict:
        marker_prefix = "<!-- ai-pr-reviewer:summary:"
        # List discussions to find existing summary
        discussions_url = f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}/discussions"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(discussions_url) as resp:
                resp.raise_for_status()
                discussions = await resp.json()
                for d in discussions:
                    notes = d.get("notes", [])
                    if not notes:
                        continue
                    n0 = notes[0]
                    nbody = n0.get("body", "")
                    if marker_prefix in nbody:
                        # Update note
                        note_id = n0.get("id")
                        disc_id = d.get("id")
                        update_url = f"{discussions_url}/{disc_id}/notes/{note_id}"
                        async with session.put(update_url, json={"body": body}) as uresp:
                            uresp.raise_for_status()
                            return await uresp.json()
        # Create new general discussion
        create_url = f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}/discussions"
        payload = {"body": body}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(create_url, json=payload) as cresp:
                cresp.raise_for_status()
                return await cresp.json()

    async def _get_existing_markers_map(self, pr_id: str) -> Dict[str, tuple]:
        marker_prefix = "<!-- ai-pr-reviewer:"
        discussions_url = f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}/discussions"
        existing: Dict[str, tuple] = {}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(discussions_url) as resp:
                if resp.status != 200:
                    return existing
                discussions = await resp.json()
                for discussion in discussions:
                    disc_id = discussion.get("id")
                    for note in discussion.get("notes", []):
                        body = note.get("body", "")
                        marker = self._extract_marker(body)
                        if marker:
                            existing[marker] = (disc_id, note.get("id"), body)
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

    async def _update_discussion_note(
        self, pr_id: str, discussion_id: int, note_id: int, body: str
    ) -> None:
        update_url = f"{self.api_base}/api/v4/projects/{self.project_id}/merge_requests/{pr_id}/discussions/{discussion_id}/notes/{note_id}"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.put(update_url, json={"body": body}) as resp:
                if resp.status >= 400:
                    error_text = await resp.text()
                    raise Exception(
                        f"GitLab API error updating note {note_id}: {resp.status} {error_text}"
                    )

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
    ) -> dict:
        comment_body = message
        position_payload = {
            "position_type": "text",
            "new_path": new_file_path,
            "old_path": old_file_path,
            "base_sha": base_sha,
            "start_sha": self._start_sha or base_sha,
            "head_sha": head_sha,
            "new_line": line,
        }

        if end_line and end_line != line:
            comment_body = f"**Lines: {line}-{end_line}**\n{message}"

            # This is a multiline comment
            position_payload["line_code"] = f"{head_sha}_{line}_{end_line}"
            position_payload["line_range"] = {
                "start": {
                    "line_code": f"{head_sha}_{line}_{line}",
                    "type": "new",
                    "new_line": line,
                },  # Assuming comments are on new lines
                "end": {
                    "line_code": f"{head_sha}_{line}_{end_line}",
                    "type": "new",
                    "new_line": end_line,
                },  # Assuming comments are on new lines
            }
        else:
            # This is a single-line comment
            position_payload["new_line"] = line
            position_payload["line_code"] = f"{head_sha}_{line}_{line}"

        return {
            "body": comment_body,
            "position": position_payload,
        }

    def _save_failed_gitlab_comments(
        self, pr_id: str, failed_comments: List[Dict]
    ) -> None:
        """Save failed GitLab comments to a debug file with enhanced details."""
        import json
        import os

        # Create debug directory if it doesn't exist
        os.makedirs("debug/gitlab_failures", exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"debug/gitlab_failures/failed_comments_pr_{pr_id}_{timestamp}.json"

        # Enhance the failed comments with more details
        enhanced_failed_comments = []
        for comment in failed_comments:
            # Get the original position data
            position = comment.get("comment", {}).get("position", {})

            # Create enhanced comment with more debugging information
            enhanced_comment = {
                "index": comment.get("index"),
                "error": comment.get("error"),
                "status_code": comment.get("status_code"),
                "file_path": comment.get("file_path") or position.get("new_path"),
                "line": comment.get("line") or position.get("new_line"),
                "position_data": position,
                "comment_body": comment.get("comment", {}).get("body", ""),
                "stack_trace": traceback.format_stack() if "error" in comment else None,
                "timestamp": datetime.now().isoformat(),
            }
            enhanced_failed_comments.append(enhanced_comment)

        failed_data = {
            "timestamp": datetime.now().isoformat(),
            "pr_id": pr_id,
            "project_id": self.project_id,
            "api_base": self.api_base,  # Add API base URL for debugging
            "failed_count": len(failed_comments),
            "failed_comments": enhanced_failed_comments,
            "environment_info": self._get_environment_info(),
        }

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(failed_data, f, ensure_ascii=False, indent=2)
            print(f"📝 Saved detailed GitLab comment failures to: {filename}")
        except Exception as e:
            print(f"Failed to save GitLab comment failures: {e}")

    def _get_environment_info(self) -> Dict:
        """Collect environment information for debugging."""
        import platform
        import sys

        return {
            "python_version": sys.version,
            "platform": platform.platform(),
            "aiohttp_version": aiohttp.__version__,
            "timestamp": datetime.now().isoformat(),
        }
