import argparse

from .clients import AzureDevOpsClient, GitHubClient, GitLabClient, PullRequestClient
from .config import load_config
from .utils.gemini_analyze import analyze_code


def get_client(platform: str, config: dict) -> PullRequestClient:
    """Factory function to get the appropriate PR client."""
    if platform.lower() == "azure":
        return AzureDevOpsClient(
            org_url=config["ORG_URL"],
            project=config["PROJECT"],
            repo_id=config["REPO_ID"],
            pat=config["AUTH_TOKEN"],  # Use pat for Azure client init
            platform=platform,
        )
    # Add conditions for other platforms
    elif platform.lower() == "github":
        return GitHubClient(
            org_url=config["ORG_URL"],
            project=config["PROJECT"],
            repo_id=config["REPO_ID"],
            auth_token=config["AUTH_TOKEN"],
            platform=platform,
        )
    elif platform.lower() == "gitlab":
        return GitLabClient(
            org_url=config["ORG_URL"],
            project=config["PROJECT"],
            repo_id=config["REPO_ID"],
            auth_token=config["AUTH_TOKEN"],
            platform=platform,
        )
    else:
        raise ValueError(f"Unsupported platform: {platform}")


async def run_ai_review_process(platform: str):
    """Orchestrates the AI review process for a given platform."""
    config = load_config(platform)
    gemini_api_key = config["GEMINI_API_KEY"]
    ai_model = config["AI_MODEL"]

    # Use the appropriate client for remote platforms
    client = get_client(platform, config)
    pr_id = config["PR_ID"]

    # Run the AI analysis and get comments directly
    review_comments = await analyze_code(
        pr_id=pr_id,
        api_key=gemini_api_key,
        model=ai_model,
        client=client,
    )
    print(f"Generated {len(review_comments)} review comments.")

    # Post the comment back to the PR (for remote platforms)
    for comment in review_comments:
        _ = await client.post_comment(
            pr_id, comment["body"], comment["position"]
        )

    print(f"Successfully posted comments to {platform} PR #{pr_id}.")


async def main():
    parser = argparse.ArgumentParser(
        description="Run AI code review for a given platform."
    )
    parser.add_argument("platform", help="The Git platform (azure, github, gitlab)")
    args = parser.parse_args()

    try:
        await run_ai_review_process(args.platform)
    except EnvironmentError as e:
        print(f"Configuration Error: {e}")
    except ValueError as e:
        print(f"Platform Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def cli_entry():
    import asyncio

    asyncio.run(main())
