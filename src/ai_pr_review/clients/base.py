import base64
from abc import ABC, abstractmethod
from typing import Tuple



class PullRequestClient(ABC):
    """
    Abstract Base Class for Git platform Pull Request clients.
    Defines the common interface for interacting with PRs.
    """

    def __init__(self, org_url: str, project: str, repo_id: str, auth_token: str):
        self.org_url = org_url
        self.project = project
        self.repo_id = repo_id
        self.auth_token = auth_token  # Generic term for authentication token

    @abstractmethod
    def get_pr_details(self, pr_id: str) -> Tuple[str, str, str, str]:
        """
        Fetches details for a given Pull Request ID.

        Returns:
            Tuple containing (title, description, source_branch, target_branch).
        """
        pass

    @abstractmethod
    def get_pr_diff(self, pr_id: str) -> str:
        """
        Fetches the diff content for a given Pull Request ID.

        Returns:
            String containing the diff.
        """
        pass

    @abstractmethod
    def post_comment(self, pr_id: str, thread_id: int, content: str) -> dict:
        """
        Posts a comment to a specific thread on a Pull Request.

        Args:
            pr_id: The Pull Request ID.
            thread_id: The ID of the thread to comment on (0 for a new thread).
            content: The comment content.

        Returns:
            A dictionary containing the response from the API.
        """
        pass

    # Helper method for basic auth, can be moved or adapted
    def _base64_encode(self, data: str) -> str:
        """Helper to base64 encode data."""
        return base64.b64encode(data.encode()).decode()
