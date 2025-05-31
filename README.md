# Gemini AI Code Reviewer

A GitHub Action that automatically reviews pull requests using Google's Gemini AI.

## Features

- Review your PRs using Gemini API
- Give use comments and suggestions to improve the source codes

## Setup

1. To use this GitHub Action, you need an Gemini API key. If you don't have one, sign up for an API key
   at [Google AI Studio](https://makersuite.google.com/app/apikey).

2. Add the Gemini API key as a GitHub Secret in your repository with the name `GEMINI_API_KEY`. You can find more
   information about GitHub Secrets [here](https://docs.github.com/en/actions/reference/encrypted-secrets).

3. Create a `.github/workflows/code-reviewer-action.yml` file in your repository and add the following content:

- Github action:

  ```yaml
  name: Gemini AI Code Reviewer

  on:
    issue_comment:
      types: [created]
  permissions: write-all
  jobs:
    gemini-code-review:
      runs-on: ubuntu-latest
      if: |
        github.event.issue.pull_request &&
        contains(github.event.comment.body, '/ai-review')
      steps:
        - name: Checkout Repo
          uses: actions/checkout@v3

        - name: Run Gemini AI Code Reviewer
          uses: HoangNguyen0403/ai_code_reviewer@latest
          with:
            GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
            GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
            AI_MODEL: 'gemini-2.5-flash-preview-05-20' # Optional
            FILES_EXCLUDE: ['**/node_modules/**', '**/dist/**', '**/build/**'] # Optional
  ```

- Gitlab CI:

  ```yaml
  workflow:
    rules:
      - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_EVENT_TYPE == "opened"' # Or synchronize etc.
        when: always # Trigger on PR open/update if you want baseline analysis
  stages:
    - code-review

  gemini_code_review:
    stage: code-review
    image: python:3.10
    before_script:
      - python -m pip install --upgrade pip
      - pip install --no-cache-dir --upgrade ai-pr-reviewer
    variables:
      GITLAB_API_URL: "https://gitlab.com/api/v4"
      CI_PROJECT_NAMESPACE: "$CI_PROJECT_NAMESPACE"
      CI_PROJECT_ID: "$CI_PROJECT_ID"
      CI_MERGE_REQUEST_IID: "$CI_MERGE_REQUEST_IID"
      GITLAB_TOKEN: "$CI_JOB_TOKEN"
      GEMINI_API_KEY: "$GEMINI_API_KEY"
      AI_MODEL: "gemini-2.5-flash-preview-05-20" # Optional
      FILES_EXCLUDE: "['**/node_modules/**', '**/dist/**', '**/build/**']" # Optional
    script:
      - |
        latest_comment=$(python -c "import gitlab; gl = gitlab.Gitlab('$GITLAB_URL', private_token='$GITLAB_TOKEN'); mr = gl.projects.get($CI_PROJECT_ID).mergerequests.get($CI_MERGE_REQUEST_IID); notes = mr.notes.list(order_by='created_at', sort='desc'); print(notes[0].body if notes else '')")
        echo "Latest comment: $latest_comment"
        if [[ "$latest_comment" != *"/ai-pr-reviewer"* ]]; then
          echo "No /ai-pr-reviewer comment found. Skipping job."
          exit 0
        fi
      - ai-pr-reviewer gitlab
  ```

- Azure Devops CI:

  ```yaml
  trigger: none  # Prevents automatic triggers; pipeline is run manually or via REST API
  pr: none

  pool:
    vmImage: 'ubuntu-latest'

  steps:
    - task: UsePythonVersion@0
      inputs:
        versionSpec: '3.10'
    - script: |
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
        GEMINI_API_KEY: $(GEMINI_API_KEY)
        AI_MODEL: "gemini-2.5-flash-preview-05-20" # Optional
        FILES_EXCLUDE: "['**/node_modules/**', '**/dist/**', '**/build/**']" # Optional      
  ```

> if you don't set `GEMINI_MODEL`, the default model is `gemini-2.0-flash`. `gemini-2.0-flash` can be used for generating code, extracting data, edit text, and more. Best for tasks balancing performance and cost. For the detailed information about the models, please refer to [Gemini models](https://ai.google.dev/gemini-api/docs/models/gemini).

4. Commit codes to your repository, and working on your pull requests.

5. When you're ready to review the PR, you can trigger the workflow by commenting `/ai-review` in the PR.

## How It Works

This GitHub Action uses the Gemini AI API to provide code review feedback. It works by:

1. **Analyzing the changes**: It grabs the code modifications from your pull request and filters out any files you don't want reviewed.
2. **Consulting the Gemini model**: It sends chunks of the modified code to the Gemini for analysis.
3. **Providing feedback**: Gemini AI examines the code and generates review comments.
4. **Delivering the review**: The Action adds the comments directly to your pull request on GitHub.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more information.
