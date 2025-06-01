import argparse
import json

from .clients import AzureDevOpsClient, GitHubClient, GitLabClient, PullRequestClient
from .config import load_config
from .utils.gemini_analyze import analyze_code  # Assuming analyze_code remains in utils


def get_client(platform: str, config: dict) -> PullRequestClient:
    """Factory function to get the appropriate PR client."""
    if platform.lower() == "azure":
        return AzureDevOpsClient(
            org_url=config["ORG_URL"],
            project=config["PROJECT"],
            repo_id=config["REPO_ID"],
            pat=config["AUTH_TOKEN"],  # Use pat for Azure client init
        )
    # Add conditions for other platforms
    elif platform.lower() == "github":
        return GitHubClient(
            org_url=config["ORG_URL"],
            project=config["PROJECT"],
            repo_id=config["REPO_ID"],
            auth_token=config["AUTH_TOKEN"],
        )
    elif platform.lower() == "gitlab":
        return GitLabClient(
            org_url=config["ORG_URL"],
            project=config["PROJECT"],
            repo_id=config["REPO_ID"],
            auth_token=config["AUTH_TOKEN"],
        )
    # elif platform.lower() == "local":
    #      return LocalClient(...)
    else:
        raise ValueError(f"Unsupported platform: {platform}")


async def run_ai_review_process(platform: str):
    """Orchestrates the AI review process for a given platform."""
    config = load_config(platform)
    output_file = config["OUTPUT_FILE"]
    gemini_api_key = config["GEMINI_API_KEY"]
    ai_model = config["AI_MODEL"]

    # For local mode, diff and details might be obtained differently
    if platform.lower() == "local":
        # Implement local git diff and commit message fetching
        # For now, using placeholders
        diff = "Local diff content"
        pr_title = "Local Commit Title"
        pr_description = "Local Commit Description"
        print(f"Running local review for commit {config.get('COMMIT_SHA', 'N/A')}")
    else:
        # Use the appropriate client for remote platforms
        client = get_client(platform, config)
        pr_id = config["PR_ID"]
        (
            pr_title,
            pr_description,
            source_branch,
            target_branch,
        ) = await client.get_pr_details(pr_id)
        diff = await client.get_pr_diff(pr_id)
        print(f"Fetched diff for {platform} PR {pr_id}")
        print(f"PR Diff {diff}")

        # Optional: Post a comment back to the PR

    # Run the AI analysis
    await analyze_code(
        diff=diff,
        pr_title=pr_title,
        pr_description=pr_description,
        api_key=gemini_api_key,
        output_file=output_file,
        model=ai_model,
        platform=platform,  # Pass the platform to analyze_code
    )
    print(f"Review comments written to {output_file}")

    # Read the AI review output
    with open(output_file, "r") as f:
        review_comments = json.load(f)

    # Post the comment back to the PR (for remote platforms)
    # if platform.lower() != "local":
    #     for comment in review_comments:
    #         commentResponse = client.post_comment(
    #             pr_id=pr_id,
    #             file_path=comment["file"],
    #             line=comment["line"],
    #             message=comment["message"],
    #         )
    #     print(f"{platform} Commented at {comment['file']}: {commentResponse}")


async def main():
    parser = argparse.ArgumentParser(
        description="Run AI code review for a given platform."
    )
    parser.add_argument(
        "platform", help="The Git platform (azure, github, gitlab, local)"
    )
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
