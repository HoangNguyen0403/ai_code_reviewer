import base64
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Optional


class PullRequestClient(ABC):
    """
    Abstract Base Class for Git platform Pull Request clients.
    Defines the common interface for interacting with PRs.
    """

    def __init__(
        self, org_url: str, project: str, repo_id: str, auth_token: str, platform: str
    ):
        self.org_url = org_url
        self.project = project
        self.repo_id = repo_id
        self.auth_token = auth_token  # Generic term for authentication token
        self.platform = platform

    @abstractmethod
    async def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str, str, str]:
        """
        Fetches details for a given Pull Request ID.

        Returns:
            Tuple containing (title, description, source_branch, target_branch, head_sha, base_sha).
        """
        pass

    @abstractmethod
    async def get_pr_diff(self, pr_id: str) -> str:
        """
        Fetches the diff content for a given Pull Request ID.

        Returns:
            String containing the diff.
        """
        pass

    @abstractmethod
    async def post_comment(self, pr_id: str, comment: Dict) -> dict:
        """Post a single formatted comment to a Pull Request.

        Args:
            pr_id: The Pull Request ID.
            comment: A provider-formatted comment payload created by
                `format_comment_payload` for this client.

        Returns: API response as dict.
        """
        pass

    @abstractmethod
    async def post_comments_batch(self, pr_id: str, comments: List[Dict]) -> bool:
        """Submit multiple comments to the PR in a batch. Return True if all succeed."""
        pass

    @abstractmethod
    async def post_summary_comment(self, pr_id: str, body: str) -> dict:
        """Post or update a top-level summary comment on the PR."""
        pass

    @abstractmethod
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
        """
        Formats a generic payload for posting a comment. Subclasses should
        override to return platform-specific payloads expected by their APIs.
        Args:
            old_file_path/new_file_path: File paths.
            line: Target new line.
            message: Comment body.
            head_sha/base_sha: Commit SHAs (used by some providers).
            end_line: Optional end line for range comments.
            diff_position/start_diff_position/end_diff_position: Optional diff indices
                (platform-specific, e.g., GitHub unified diff position mapping).
        Returns:
            A dictionary representing the comment payload.
        """
        return {
            "old_file_path": old_file_path,
            "new_file_path": new_file_path,
            "line": line,
            "end_line": end_line,
            "body": message,
            "head_sha": head_sha,
            "base_sha": base_sha,
            "diff_position": diff_position,
            "start_diff_position": start_diff_position,
            "end_diff_position": end_diff_position,
        }

    # Helper method for basic auth, can be moved or adapted
    def _base64_encode(self, data: str) -> str:
        """Helper to base64 encode data."""
        return base64.b64encode(data.encode()).decode()
