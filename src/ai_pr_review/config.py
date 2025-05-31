import os


def get_env_var(name: str) -> str:
    """Loads a required environment variable."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value


def load_config(platform: str):
    """Loads configuration based on the specified platform."""
    config = {
        "GEMINI_API_KEY": get_env_var("GEMINI_API_KEY"),
        "OUTPUT_FILE": os.environ.get(
            "OUTPUT_FILE", "gemini_review.json"
        ),  # Optional env var with default
    }

    if platform.lower() == "azure":
        config["ORG_URL"] = get_env_var("AZURE_ORG_URL")
        config["PROJECT"] = get_env_var("AZURE_PROJECT")
        config["REPO_ID"] = get_env_var("AZURE_REPO_ID")
        config["PR_ID"] = get_env_var("AZURE_PULL_REQUEST_ID")
        config["AUTH_TOKEN"] = get_env_var("AZURE_PAT")
    elif platform.lower() == "github":
        config["ORG_URL"] = get_env_var(
            "GITHUB_API_URL"
        )  # e.g., https://api.github.com
        config["PROJECT"] = get_env_var("GITHUB_REPOSITORY").split("/")[0]  # Owner
        config["REPO_ID"] = get_env_var("GITHUB_REPOSITORY").split("/")[1]  # Repo name
        config["PR_ID"] = get_env_var("GITHUB_PULL_REQUEST_ID")
        config["AUTH_TOKEN"] = get_env_var("GITHUB_TOKEN")
    elif platform.lower() == "gitlab":
        config["ORG_URL"] = get_env_var(
            "GITLAB_API_URL"
        )  # e.g., https://gitlab.com/api/v4
        config["PROJECT"] = get_env_var("CI_PROJECT_NAMESPACE")  # Group/User
        config["REPO_ID"] = get_env_var("CI_PROJECT_ID")  # Project ID
        config["PR_ID"] = get_env_var("CI_MERGE_REQUEST_IID")  # Merge Request IID
        config["AUTH_TOKEN"] = get_env_var("GITLAB_TOKEN")
    elif platform.lower() == "local":
        # Local mode might not need all these, or might get them differently
        config["REPO_PATH"] = os.environ.get("LOCAL_REPO_PATH", ".")
        config["COMMIT_SHA"] = get_env_var("LOCAL_COMMIT_SHA")
        # Local mode doesn't need ORG_URL, PROJECT, REPO_ID, PR_ID, AUTH_TOKEN
        pass
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    return config
