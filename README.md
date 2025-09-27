# Gemini AI Code Reviewer

Review pull requests automatically in CI using Google's Gemini API with inline comments, idempotent updates, and a concise summary for human reviewers.

## Highlights

- Diff-aware inline suggestions posted directly on GitHub, GitLab, and Azure DevOps pull requests.
- Idempotent updates that refresh previous comments instead of spamming new ones.
- Optional summary comment that captures the most important findings for reviewers.
- Works from CI pipelines or your local machine using the same CLI entry point.

## Supported platforms

- GitHub (GitHub Actions or any workflow shell)
- GitLab (GitLab CI/CD)
- Azure DevOps (classic or YAML pipelines)

## Prerequisites

### Common requirements

- A Google Gemini API key stored as `GOOGLE_API_KEY`. Create one in [Google AI Studio](https://makersuite.google.com/app/apikey).
- Python 3.10+ when running the CLI yourself (GitHub Action runs it for you).
- Outbound network access from your runner to `api.github.com`, `gitlab.com` (or your self-hosted domain), and `dev.azure.com` as needed.

### Platform access tokens

| Platform | Variable | Scope / permissions |
| --- | --- | --- |
| GitHub | `GITHUB_TOKEN` | `contents: read`, `pull-requests: write` (the default workflow token works if permissions are elevated). |
| GitLab | `GITLAB_TOKEN` | API scope. Use `$CI_JOB_TOKEN` for first-party pipelines or a PAT otherwise. |
| Azure DevOps | `AZURE_PAT` | `Code (Read & Write)` scope with access to the target project and repository. |

## Quick start

1. Store your Gemini key in the platform secret store (for GitHub: `Settings → Secrets → Actions → New repository secret`).
2. Copy the integration template below that matches your platform and drop it into your CI configuration.
3. Trigger the job and wait for inline comments and a summary to appear on the pull request.

### GitHub Actions (pull request or manual trigger)

```yaml
name: Gemini AI Review

on:
  pull_request_target:
    types: [opened, synchronize, reopened]
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write

jobs:
  ai-review:
    runs-on: ubuntu-latest
    steps:
      - name: Run Gemini AI Code Reviewer
        uses: HoangNguyen0403/ai_code_reviewer@latest
        with:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          AI_MODEL: gemini-2.5-flash-preview-05-20 # Optional override
          FILES_EXCLUDE: '**/dist/**,**/node_modules/**' # Optional
```

This workflow runs automatically on PR updates and can also be launched manually via the **Run workflow** button.

#### Triggering the review from a `/ai-review` comment

If you prefer an on-demand flow, hook into the `issue_comment` event and run the CLI directly:

```yaml
on:
  issue_comment:
    types: [created]

jobs:
  ai-review:
    if: github.event.issue.pull_request != '' && contains(github.event.comment.body, '/ai-review')
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Run Gemini AI Code Reviewer
        run: |
          python -m pip install --upgrade pip
          pip install --no-cache-dir ai-pr-reviewer
          ai-pr-reviewer github
        env:
          GITHUB_API_URL: ${{ github.api_url }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          GITHUB_PULL_REQUEST_ID: ${{ github.event.issue.number }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          FILES_EXCLUDE: '**/dist/**,**/node_modules/**' # Optional
```

### GitLab CI/CD

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      when: always

stages:
  - code-review

gemini_code_review:
  stage: code-review
  image: python:3.10
  variables:
    GITLAB_API_URL: "https://gitlab.com/api/v4"
    GOOGLE_API_KEY: "$GOOGLE_API_KEY"
    GITLAB_TOKEN: "$CI_JOB_TOKEN"
    AI_MODEL: "gemini-2.5-flash-preview-05-20" # Optional
    FILES_EXCLUDE: "**/dist/**,**/node_modules/**" # Optional
  script:
    - python -m pip install --upgrade pip
    - pip install --no-cache-dir --upgrade ai-pr-reviewer
    - export CI_PROJECT_NAMESPACE="${CI_PROJECT_NAMESPACE}"
    - export CI_PROJECT_ID="${CI_PROJECT_ID}"
    - export CI_MERGE_REQUEST_IID="${CI_MERGE_REQUEST_IID}"
    - ai-pr-reviewer gitlab
```

To make the job on-demand, guard the final command behind a `/ai-review` comment check using the GitLab API.

### Azure DevOps Pipelines

```yaml
trigger: none
pr: none

pool:
  vmImage: 'ubuntu-latest'

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.10'
  - bash: |
      python -m pip install --upgrade pip
      pip install --no-cache-dir --upgrade ai-pr-reviewer
      ai-pr-reviewer azure
    displayName: 'Run AI PR Reviewer'
    env:
      AZURE_ORG_URL: $(AZURE_ORG_URL)
      AZURE_PROJECT: $(AZURE_PROJECT)
      AZURE_REPO_ID: $(AZURE_REPO_ID)
      AZURE_PULL_REQUEST_ID: $(AZURE_PULL_REQUEST_ID)
      AZURE_PAT: $(AZURE_PAT)
      GOOGLE_API_KEY: $(GOOGLE_API_KEY)
      AI_MODEL: "gemini-2.5-flash-preview-05-20" # Optional
      FILES_EXCLUDE: "**/dist/**,**/node_modules/**" # Optional
```

Run the pipeline manually or trigger it with REST when you need an AI review.

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install ai-pr-reviewer
export GOOGLE_API_KEY=...
export GITHUB_API_URL=https://api.github.com
export GITHUB_REPOSITORY=owner/repo
export GITHUB_PULL_REQUEST_ID=123
export GITHUB_TOKEN=ghp_your_token
ai-pr-reviewer github
```

Swap the environment variables for `gitlab` or `azure` and call `ai-pr-reviewer gitlab` / `ai-pr-reviewer azure` respectively. Set `DRY_RUN=true` to collect debug artifacts without posting comments.

## Configuration reference

| Variable | Default | Description |
| --- | --- | --- |
| `GOOGLE_API_KEY` | — | Gemini API key (required). |
| `AI_MODEL` | `gemini-2.0-flash-lite-001` | Model name passed to the Gemini API. |
| `FILES_EXCLUDE` | `*.md,*.txt,package-lock.json,pubspec.yaml,*.g.dart,*.freezed.dart,*.gr.dart,*.json,*.graphql` | Comma-separated glob patterns excluded from analysis. |
| `AI_TEMPERATURE` | `0.1` | Sampling temperature for Gemini. |
| `AI_TIMEOUT` | `30` | Seconds to wait for each Gemini call before timing out. |
| `AI_REQUESTS_PER_MINUTE` | `25` | Rate limit applied between Gemini calls. |
| `AI_MIN_REQUEST_INTERVAL` | `3` | Minimum seconds between Gemini calls. |
| `AI_RETRY_DELAY` | `30` | Wait time (seconds) after hitting a rate limit error. |
| `AI_MAX_RETRIES` | `3` | Retry attempts per Gemini call. |
| `AI_BATCH_SIZE` | `5` | Number of diff hunks processed per batch. |
| `AI_BATCH_DELAY` | `15` | Seconds between batches. |
| `DEBUG` | `false` | Enable verbose logging and debug JSON exports. |
| `DRY_RUN` | `false` | Skip posting comments; still writes debug output under `debug/`. |

Platform-specific essentials:

| Platform | Must provide | Notes |
| --- | --- | --- |
| GitHub | `GITHUB_API_URL`, `GITHUB_REPOSITORY`, `GITHUB_PULL_REQUEST_ID`, `GITHUB_TOKEN` | `GITHUB_API_URL` defaults to `https://api.github.com`. The workflow example sets the rest automatically. |
| GitLab | `GITLAB_API_URL`, `CI_PROJECT_NAMESPACE`, `CI_PROJECT_ID`, `CI_MERGE_REQUEST_IID`, `GITLAB_TOKEN` | When using GitLab.com the defaults are available from CI variables. |
| Azure DevOps | `AZURE_ORG_URL`, `AZURE_PROJECT`, `AZURE_REPO_ID`, `AZURE_PULL_REQUEST_ID`, `AZURE_PAT` | The PAT must have access to the project and repository. |

## What to expect

- Inline review comments placed on the exact diff ranges where the AI found issues.
- A pull request summary comment (with the `<!-- ai-pr-reviewer:summary:... -->` marker) that updates idempotently.
- Debug artifacts written to the `debug/` folder whenever `DEBUG=true` or a run fails, including raw model responses and submission logs.

## Troubleshooting

- **Missing environment variable**: The CLI stops immediately and prints which variable is absent. Double-check the `env` block in your job.
- **Permission errors**: Ensure the token/PAT has write access to pull requests and that the job grants `pull-requests: write`.
- **Rate limiting**: Lower `AI_REQUESTS_PER_MINUTE` or raise `AI_BATCH_DELAY` if you see repeated 429 responses from the Gemini API.
- **Comment placement looks off**: Confirm the runner checked out the latest code and that the PR wasn't force-pushed between runs.
