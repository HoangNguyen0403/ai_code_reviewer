import fnmatch
import json
import os
from typing import Any, Dict, List

import requests

EXCLUDE_PATTERN_DEFAULT = "*.md,*.txt,package-lock.json,pubspec.yaml,*.g.dart,*.freezed.dart,*.gr.dart,*.json,*.graphql"


def create_prompt(
    diff: str, pr_title: str, pr_description: str, platform: str = "generic"
) -> str:
    external_rules = os.environ.get("OTHER_REVIEW_RULES", "")
    prompt = (
        f"You are an expert software engineer performing a code review for a pull/merge request on {platform}.\n"
        f"PR Title: {pr_title}\n"
        f"PR Description: {pr_description}\n"
        f"Diff:\n{diff}\n"
        f"Additional Review Rules:\n{external_rules}\n"
        "Please review the code changes according to the following criteria, following best practices:\n"
        "1. **Correctness**: Does the code do what it claims? Are there any logic errors, bugs, or missing edge cases?\n"
        "2. **Security**: Are there any vulnerabilities, unsafe patterns, or risks of data leaks?\n"
        "3. **Performance**: Is the code efficient? Are there unnecessary computations, memory issues, or scalability concerns?\n"
        "4. **Readability**: Is the code clear, well-structured, and easy to understand? Are naming conventions and formatting consistent?\n"
        "5. **Maintainability**: Is the code modular, testable, and easy to extend? Are there code smells or technical debt?\n"
        "6. **Adherence to Project Standards**: Does the code follow the project's style guide, architectural patterns, and documentation requirements?\n"
        "7. **Testing**: Are there sufficient and meaningful tests? Are edge cases covered?\n"
        "8. **Documentation**: Are public APIs, complex logic, and important decisions documented?\n"
        "For each issue found, provide a structured JSON object with: file, line, severity (info/warning/error), category (bug, style, performance, etc.), suggestion, and rationale.\n"
        "Be concise, actionable, and professional. If no issues, reply with an empty JSON array []."
    )
    return prompt


def get_ai_response(
    prompt: str, api_key: str, model: str = "gemini-pro"
) -> List[Dict[str, Any]]:
    """
    Send the prompt to Gemini API and parse the JSON response as a list of comments.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    response = requests.post(url, headers=headers, data=json.dumps(data), timeout=60)
    response.raise_for_status()
    try:
        candidates = response.json()["candidates"]
        content = candidates[0]["content"]["parts"][0]["text"]
        comments = json.loads(content)
        if not isinstance(comments, list):
            raise ValueError("AI response is not a list")
        return comments
    except Exception as e:
        raise RuntimeError(f"Failed to parse Gemini response: {e}")


def create_review_comment(comment: Dict[str, Any], output_file: str) -> None:
    """
    Write a single review comment to the output file in JSONL format.
    """
    with open(output_file, "a") as f:
        f.write(json.dumps(comment) + "\n")


def filter_diff(diff: str, exclude_patterns: list) -> str:
    filtered = []
    current_file = None
    exclude = False
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git"):
            parts = line.split(" b/")
            if len(parts) > 1:
                current_file = parts[1].strip()
                exclude = any(
                    fnmatch.fnmatch(current_file, pat.strip())
                    for pat in exclude_patterns
                )
            else:
                current_file = None
                exclude = False
        if not exclude:
            filtered.append(line)
    return "".join(filtered)


def analyze_code(
    diff: str,
    pr_title: str,
    pr_description: str,
    api_key: str,
    output_file: str,
    platform: str = "generic",
    model: str = "gemini-pro",
) -> None:
    """
    Analyze the code diff using Gemini and write review comments to the output file.
    """
    env_patterns = os.environ.get("FILES_EXCLUDE", "")
    all_patterns = EXCLUDE_PATTERN_DEFAULT
    if env_patterns:
        all_patterns += "," + env_patterns
    exclude_patterns = [p.strip() for p in all_patterns.split(",") if p.strip()]
    filtered_diff = filter_diff(diff, exclude_patterns)
    prompt = create_prompt(filtered_diff, pr_title, pr_description, platform)
    comments = get_ai_response(prompt, api_key, model)
    for comment in comments:
        create_review_comment(comment, output_file)
