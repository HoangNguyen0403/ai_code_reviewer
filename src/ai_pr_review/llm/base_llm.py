from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..clients import PullRequestClient
from ..utils import DiffProcessor, LineNumberMapper


@dataclass
class AIAnalysisConfig:
    """Configuration for AI analysis."""

    model: str
    temperature: float
    timeout: int
    debug: bool

    # Rate limiting configuration
    requests_per_minute: int  # Conservative default for free tier
    min_request_interval: float  # Seconds between requests
    retry_delay: int  # Seconds to wait on rate limit error
    max_retries: int  # Maximum retry attempts
    batch_size: int  # Number of hunks to process in each batch
    batch_delay: int  # Seconds to wait between batches

    @classmethod
    def from_env(cls, model: str, debug: bool, **overrides) -> "AIAnalysisConfig":
        """Create config from environment variables with overrides."""
        import os

        config = cls(
            model=model,
            debug=debug,
            temperature=float(os.environ.get("AI_TEMPERATURE", 0.1)),
            timeout=int(os.environ.get("AI_TIMEOUT", 30)),
            requests_per_minute=int(os.environ.get("AI_REQUESTS_PER_MINUTE", 25)),
            min_request_interval=float(os.environ.get("AI_MIN_REQUEST_INTERVAL", 3)),
            retry_delay=int(os.environ.get("AI_RETRY_DELAY", 30)),
            max_retries=int(os.environ.get("AI_MAX_RETRIES", 3)),
            batch_size=int(os.environ.get("AI_BATCH_SIZE", 5)),
            batch_delay=int(os.environ.get("AI_BATCH_DELAY", 15)),
        )

        # Apply any overrides
        for key, value in overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)
            else:
                raise ValueError(f"Invalid override key for AIAnalysisConfig: '{key}'")

        return config


@dataclass
class CodeReviewComment:
    """Structured representation of a code review comment."""

    hunk_index: int
    old_file_path: str
    new_file_path: str
    new_line: int
    severity: str  # info, warning, error
    category: str  # bug, style, performance, etc.
    suggestion: str
    rationale: str
    end_line: Optional[int] = None
    original_ai_line: Optional[int] = None
    warning: Optional[str] = None


class BaseLLMProvider(ABC):
    def __init__(self, config: AIAnalysisConfig):
        self.config = config
        self._client = None

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of the LLM provider."""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the LLM client and any required resources."""
        pass

    @abstractmethod
    async def generate_response(self, prompt: str) -> str:
        """Generate a response from the LLM given a prompt."""
        pass

    @abstractmethod
    def parse_response(self, response: str) -> List[CodeReviewComment]:
        """Parse the LLM response into structured comments."""
        pass

    @abstractmethod
    async def analyze_hunk(
        self, hunk: Dict, pr_title: str, pr_description: str, platform: str = "generic"
    ) -> List[CodeReviewComment]:
        """Analyze a single code hunk and return review comments."""
        pass

    async def analyze_code_with_background_submission(
        self,
        pr_id: str,
        client: PullRequestClient,
    ) -> List[Dict[str, Any]]:
        """Analyze code with background comment submission using asyncio queues."""
        import asyncio
        from asyncio import Queue
        from math import ceil

        # Initialize the provider
        await self.initialize()

        # Get PR details and diff
        pr_details = await client.get_pr_details(pr_id)
        pr_title, pr_description, source_branch, target_branch, head_sha, base_sha = (
            pr_details
        )
        diff = await client.get_pr_diff(pr_id)

        # Process diff
        diff_processor = DiffProcessor()
        line_mapper = LineNumberMapper()

        exclude_patterns = self._get_exclude_patterns()
        diff_processor.exclude_patterns = exclude_patterns
        filtered_diff = diff_processor.filter_diff(diff)
        hunks = diff_processor.split_unified_diff(filtered_diff)

        if self.config.debug:
            self._save_debug_hunks(hunks)
            print(
                f"Processing {len(hunks)} hunks in batches of {self.config.batch_size} with background submission"
            )

        # Calculate number of batches
        total_hunks = len(hunks)
        num_batches = ceil(total_hunks / self.config.batch_size)

        # Create a queue for comments to be submitted
        comment_queue = Queue()
        submission_errors = []
        submitted_batches = []

        # Create an event to signal when processing is complete
        shutdown_event = asyncio.Event()

        # Background comment submission task
        async def comment_submitter():
            """Background task to submit comments as they become available."""
            while not shutdown_event.is_set() or not comment_queue.empty():
                try:
                    # Wait for batch data with timeout
                    batch_data = await asyncio.wait_for(
                        comment_queue.get(), timeout=2.0
                    )

                    if batch_data is None:  # Sentinel to stop
                        if self.config.debug:
                            print("Background submitter received stop signal")
                        comment_queue.task_done()
                        continue  # Don't break, let the while condition handle exit

                    batch_comments, batch_num, batch_info = batch_data

                    if self.config.debug:
                        print(
                            f"📤 Background submitting batch {batch_num} ({len(batch_comments)} comments)"
                        )

                    try:
                        await self._submit_batch_comments(
                            client, pr_id, batch_comments, batch_num
                        )
                        submitted_batches.append(
                            {
                                "batch_num": batch_num,
                                "comment_count": len(batch_comments),
                                "status": "success",
                            }
                        )

                        if self.config.debug:
                            print(f"  ✅ Successfully submitted batch {batch_num}")

                    except Exception as e:
                        error_info = {
                            "batch_num": batch_num,
                            "error": str(e),
                            "comment_count": len(batch_comments),
                        }
                        submission_errors.append(error_info)
                        print(f"  ❌ Failed to submit batch {batch_num}: {e}")

                    finally:
                        comment_queue.task_done()

                except asyncio.TimeoutError:
                    # Just continue the loop - the while condition will check if we should exit
                    if (
                        self.config.debug
                        and shutdown_event.is_set()
                        and comment_queue.empty()
                    ):
                        print(
                            "Background submitter: timeout with empty queue, checking exit condition"
                        )
                    continue
                except Exception as e:
                    print(f"Background submission error: {e}")
                    # Still mark the task as done if we got an item from the queue
                    if "batch_data" in locals() and batch_data is not None:
                        comment_queue.task_done()

            if self.config.debug:
                print("Background submitter exiting cleanly")

        # Start the background submitter task
        submitter_task = asyncio.create_task(comment_submitter())

        all_mapped_comments = []
        all_formatted_comments = []

        try:
            # Process hunks in batches
            for batch_num in range(num_batches):
                start_idx = batch_num * self.config.batch_size
                end_idx = min(start_idx + self.config.batch_size, total_hunks)
                batch_hunks = hunks[start_idx:end_idx]

                if self.config.debug:
                    print(
                        f"🔄 Processing batch {batch_num + 1}/{num_batches}: hunks {start_idx}-{end_idx - 1}"
                    )

                # Process current batch
                (
                    batch_comments,
                    batch_mapped,
                    batch_formatted,
                ) = await self._process_hunk_batch(
                    batch_hunks,
                    start_idx,
                    pr_title,
                    pr_description,
                    client,
                    line_mapper,
                    head_sha,
                    base_sha,
                )

                # Accumulate results for debugging/return
                all_mapped_comments.extend(batch_mapped)
                all_formatted_comments.extend(batch_formatted)

                # Queue comments for background submission if any found
                if batch_formatted:
                    batch_info = {
                        "start_idx": start_idx,
                        "end_idx": end_idx,
                        "hunk_count": len(batch_hunks),
                    }
                    await comment_queue.put(
                        (batch_formatted, batch_num + 1, batch_info)
                    )

                    if self.config.debug:
                        print(
                            f"  📋 Queued {len(batch_formatted)} comments from batch {batch_num + 1} for submission"
                        )
                else:
                    if self.config.debug:
                        print(f"  ℹ️  No comments found in batch {batch_num + 1}")

                # Wait between batches (except for the last batch)
                if batch_num < num_batches - 1:
                    if self.config.debug:
                        print(
                            f"⏳ Waiting {self.config.batch_delay} seconds before next batch..."
                        )
                    await asyncio.sleep(self.config.batch_delay)

        finally:
            # Signal completion and wait for remaining submissions
            if self.config.debug:
                print(
                    "🏁 Analysis complete, waiting for background submissions to finish..."
                )

            # Send sentinel to stop the background task
            await comment_queue.put(None)

            # Wait for all queued items to be processed
            await comment_queue.join()

            # Signal the submitter to shut down
            shutdown_event.set()

            # Set a timeout for the submitter task to complete
            try:
                await asyncio.wait_for(submitter_task, timeout=5.0)
            except asyncio.TimeoutError:
                print(
                    "Warning: Background submitter task did not complete within timeout"
                )
                # Cancel the task if it doesn't complete in time
                submitter_task.cancel()
                try:
                    await submitter_task
                except asyncio.CancelledError:
                    print("Background submitter task was cancelled")

            # Report submission results and save summary
            if self.config.debug:
                total_submitted = sum(
                    batch["comment_count"]
                    for batch in submitted_batches
                    if batch["status"] == "success"
                )
                total_failed = len(submission_errors)

                print("\n📊 Submission Summary:")
                print(f"  ✅ Successfully submitted: {total_submitted} comments")
                if total_failed > 0:
                    print(f"  ❌ Failed submissions: {total_failed} batches")
                    for error in submission_errors:
                        print(f"    - Batch {error['batch_num']}: {error['error']}")

                # Save comprehensive submission summary
                self._save_submission_summary(submitted_batches, submission_errors)

                self._save_debug_files(all_mapped_comments, all_formatted_comments)
                print(
                    f"Completed processing {total_hunks} hunks in {num_batches} batches with background submission"
                )

        # Post a summary comment (idempotent via marker)
        try:
            summary = self._build_summary_comment(all_mapped_comments)
            if summary:
                await client.post_summary_comment(pr_id, summary)
        except Exception as e:
            print(f"Failed to post summary comment: {e}")

    async def _submit_batch_comments(
        self,
        client: PullRequestClient,
        pr_id: str,
        comments: List[Dict],
        batch_num: int,
    ) -> None:
        """Submit a batch of comments immediately with detailed debug logging."""
        import os
        from datetime import datetime

        # Create debug directory
        os.makedirs("debug/submissions", exist_ok=True)

        # Log submission attempt
        submission_log = {
            "timestamp": datetime.now().isoformat(),
            "batch_num": batch_num,
            "pr_id": pr_id,
            "comment_count": len(comments),
            "comments": comments,
            "status": "attempting",
            "provider": self.provider_name,
        }

        try:
            # DRY_RUN: write and return without posting
            try:
                from ..utils import is_dry_run
            except ImportError:
                # Fallback if is_dry_run does not exist
                def is_dry_run():
                    import os
                    return os.environ.get("AI_DRY_RUN", "0") == "1"
            if is_dry_run():
                submission_log["status"] = "dry_run"
                self._save_submission_log(submission_log)
                return

            # Submit comments using the client's batch submission method
            if hasattr(client, "post_comments_batch"):
                await client.post_comments_batch(pr_id, comments)
                submission_log["status"] = "success"
                submission_log["method"] = "batch_submission"
            else:
                # Fallback: submit comments individually with detailed tracking
                individual_results = []
                failed_comments = []

                for i, comment in enumerate(comments):
                    try:
                        await client.post_comment(pr_id, comment)
                        individual_results.append(
                            {
                                "index": i,
                                "status": "success",
                                "comment_id": comment.get("id", f"comment_{i}"),
                                "line": comment.get("line"),
                                "file_path": comment.get("path"),
                            }
                        )
                    except Exception as comment_error:
                        failed_comment = {
                            "index": i,
                            "status": "failed",
                            "error": str(comment_error),
                            "comment_data": comment,
                            "line": comment.get("line"),
                            "file_path": comment.get("path"),
                        }
                        individual_results.append(failed_comment)
                        failed_comments.append(failed_comment)

                        if self.config.debug:
                            print(
                                f"    ❌ Failed to submit individual comment {i}: {comment_error}"
                            )

                submission_log["method"] = "individual_submission"
                submission_log["individual_results"] = individual_results
                submission_log["failed_count"] = len(failed_comments)

                if failed_comments:
                    submission_log["status"] = "partial_success"
                    # Save failed comments to separate file
                    self._save_failed_comments(batch_num, failed_comments)
                else:
                    submission_log["status"] = "success"

            # Save successful submission log
            self._save_submission_log(submission_log)

        except Exception as e:
            submission_log["status"] = "failed"
            submission_log["error"] = str(e)
            submission_log["error_type"] = type(e).__name__

            # Save failed submission log
            self._save_submission_log(submission_log)

            # Save all comments that failed to submit
            self._save_failed_batch(batch_num, comments, str(e))

            # Log error but don't fail the entire process
            print(f"Error submitting batch {batch_num} comments: {e}")
            raise

    def _save_submission_log(self, submission_log: Dict) -> None:
        """Save submission log to debug file."""
        import json
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_num = submission_log.get("batch_num", "unknown")
        status = submission_log.get("status", "unknown")

        filename = f"debug/submissions/batch_{batch_num}_{status}_{timestamp}.json"

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(submission_log, f, ensure_ascii=False, indent=2)

            if self.config.debug:
                print(f"  📝 Saved submission log: {filename}")
        except Exception as e:
            print(f"Failed to save submission log: {e}")

    def _save_failed_comments(
        self, batch_num: int, failed_comments: List[Dict]
    ) -> None:
        """Save failed individual comments to debug file."""
        import json
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"debug/submissions/failed_comments_batch_{batch_num}_{timestamp}.json"
        )

        failed_data = {
            "timestamp": datetime.now().isoformat(),
            "batch_num": batch_num,
            "provider": self.provider_name,
            "failed_count": len(failed_comments),
            "failed_comments": failed_comments,
        }

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(failed_data, f, ensure_ascii=False, indent=2)

            if self.config.debug:
                print(f"  📝 Saved failed comments: {filename}")
        except Exception as e:
            print(f"Failed to save failed comments: {e}")

    def _save_failed_batch(
        self, batch_num: int, comments: List[Dict], error: str
    ) -> None:
        """Save entire failed batch to debug file."""
        import json
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"debug/submissions/failed_batch_{batch_num}_{timestamp}.json"

        failed_batch_data = {
            "timestamp": datetime.now().isoformat(),
            "batch_num": batch_num,
            "provider": self.provider_name,
            "error": error,
            "comment_count": len(comments),
            "comments": comments,
        }

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(failed_batch_data, f, ensure_ascii=False, indent=2)

            if self.config.debug:
                print(f"  📝 Saved failed batch: {filename}")
        except Exception as e:
            print(f"Failed to save failed batch: {e}")

    def _save_submission_summary(
        self, submitted_batches: List[Dict], submission_errors: List[Dict]
    ) -> None:
        """Save overall submission summary to debug file."""
        import json
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"debug/submissions/submission_summary_{timestamp}.json"

        total_submitted = sum(
            batch["comment_count"]
            for batch in submitted_batches
            if batch["status"] == "success"
        )

        summary_data = {
            "timestamp": datetime.now().isoformat(),
            "provider": self.provider_name,
            "total_batches": len(submitted_batches) + len(submission_errors),
            "successful_batches": len(
                [b for b in submitted_batches if b["status"] == "success"]
            ),
            "failed_batches": len(submission_errors),
            "total_comments_submitted": total_submitted,
            "submitted_batches": submitted_batches,
            "submission_errors": submission_errors,
        }

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(summary_data, f, ensure_ascii=False, indent=2)

            if self.config.debug:
                print(f"  📝 Saved submission summary: {filename}")
        except Exception as e:
            print(f"Failed to save submission summary: {e}")

    def _build_summary_comment(self, mapped_comments: List[Dict]) -> str:
        if not mapped_comments:
            return ""
        sev_counts = {"error": 0, "warning": 0, "info": 0}
        by_category = {}
        for c in mapped_comments:
            sev = (c.get("severity") or "info").lower()
            if sev in sev_counts:
                sev_counts[sev] += 1
            cat = c.get("category") or "general"
            by_category[cat] = by_category.get(cat, 0) + 1
        lines = [
            "### AI Review Summary",
            f"- Errors: {sev_counts['error']} | Warnings: {sev_counts['warning']} | Info: {sev_counts['info']}",
            "- By category: " + ", ".join(f"{k}: {v}" for k, v in by_category.items()),
            "",
            f"<!-- ai-pr-reviewer:summary:{int(len(mapped_comments))} -->",
        ]
        return "\n".join(lines)

    async def _process_hunk_batch(
        self,
        batch_hunks: List[Dict],
        start_hunk_index: int,
        pr_title: str,
        pr_description: str,
        client: PullRequestClient,
        line_mapper: LineNumberMapper,
        head_sha: str,
        base_sha: str,
    ) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """Process a batch of hunks with rate limiting."""
        import asyncio

        batch_comments = []
        batch_mapped = []
        batch_formatted = []

        for i, hunk in enumerate(batch_hunks):
            hunk_index = start_hunk_index + i

            try:
                # Rate limiting: wait between requests
                if i > 0:  # Don't wait before the first request in batch
                    await asyncio.sleep(self.config.min_request_interval)

                # Analyze hunk with retry logic
                ai_comments = await self._analyze_hunk_with_retry(
                    hunk, hunk_index, pr_title, pr_description, client.platform
                )

                if ai_comments:
                    # Convert to dict format for line mapping
                    comment_dicts = [
                        self._comment_to_dict(comment) for comment in ai_comments
                    ]

                    # Map to correct line numbers
                    mapped_comments = line_mapper.map_comments_to_absolute_lines(
                        comment_dicts, [hunk]
                    )

                    # Format for API
                    formatted_comments = self._format_comments_for_api(
                        mapped_comments, client, head_sha, base_sha
                    )

                    batch_comments.extend(comment_dicts)
                    batch_mapped.extend(mapped_comments)
                    batch_formatted.extend(formatted_comments)

            except Exception as e:
                print(
                    f"Error processing hunk {hunk_index} with {self.provider_name}: {e}"
                )
                continue

        return batch_comments, batch_mapped, batch_formatted

    async def _analyze_hunk_with_retry(
        self,
        hunk: Dict,
        hunk_index: int,
        pr_title: str,
        pr_description: str,
        platform: str = "generic",
    ) -> List[CodeReviewComment]:
        """Analyze a hunk with retry logic for rate limiting."""
        import asyncio

        for attempt in range(self.config.max_retries + 1):
            try:
                return await self.analyze_hunk(hunk, pr_title, pr_description, platform)

            except Exception as e:
                error_msg = str(e).lower()

                # Check if it's a rate limit error
                if (
                    "429" in error_msg
                    or "rate limit" in error_msg
                    or "resource_exhausted" in error_msg
                ):
                    if attempt < self.config.max_retries:
                        wait_time = self.config.retry_delay * (
                            attempt + 1
                        )  # Exponential backoff
                        print(
                            f"  Rate limit hit for hunk {hunk_index}, waiting {wait_time}s (attempt {attempt + 1}/{self.config.max_retries + 1})"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        print(
                            f"  Max retries exceeded for hunk {hunk_index} due to rate limiting"
                        )
                        return []
                else:
                    # Non-rate-limit error, don't retry
                    print(f"  Non-rate-limit error for hunk {hunk_index}: {e}")
                    return []

        return []

    def _comment_to_dict(self, comment: CodeReviewComment) -> Dict[str, Any]:
        """Convert CodeReviewComment to dictionary format."""
        return {
            "hunk_index": comment.hunk_index,
            "old_file_path": comment.old_file_path,
            "new_file_path": comment.new_file_path,
            "new_line": comment.new_line,
            "severity": comment.severity,
            "category": comment.category,
            "suggestion": comment.suggestion,
            "rationale": comment.rationale,
            "original_ai_line": comment.original_ai_line,
            "warning": comment.warning,
            "end_line": comment.end_line,
        }

    def _get_exclude_patterns(self) -> List[str]:
        """Get file exclude patterns from environment and defaults."""
        import os

        EXCLUDE_PATTERN_DEFAULT = "*.md,*.txt,package-lock.json,pubspec.yaml,*.g.dart,*.freezed.dart,*.gr.dart,*.json,*.graphql"
        env_patterns = os.environ.get("FILES_EXCLUDE", "")
        all_patterns = EXCLUDE_PATTERN_DEFAULT
        if env_patterns:
            all_patterns += "," + env_patterns
        return [p.strip() for p in all_patterns.split(",") if p.strip()]

    def _format_comments_for_api(
        self,
        comments: List[Dict],
        client: PullRequestClient,
        head_sha: str,
        base_sha: str,
    ) -> List[Dict]:
        """Format comments for API submission."""
        formatted_comments = []

        for comment in comments:
            if comment.get("new_line"):
                marker = self._make_idempotency_marker(comment)
                body = (
                    f"**{self.provider_name} AI Suggestion**\n"
                    f"- Severity: {comment['severity']}\n"
                    f"- Category: {comment['category']}\n"
                    f"- Suggestion: {comment['suggestion']}\n"
                    f"- Rationale: {comment['rationale']}\n"
                    f"\n<!-- ai-pr-reviewer:{marker} -->"
                )
                diff_position = comment.get("github_position")
                start_diff_position = comment.get("github_start_position") or diff_position
                end_diff_position = comment.get("github_end_position") or diff_position

                formatted_comment = client.format_comment_payload(
                    line=comment["new_line"],
                    message=body,
                    head_sha=head_sha,
                    base_sha=base_sha,
                    old_file_path=comment["old_file_path"],
                    new_file_path=comment["new_file_path"],
                    end_line=comment.get("end_line"),  # Pass the end_line
                    diff_position=diff_position,
                    start_diff_position=start_diff_position,
                    end_diff_position=end_diff_position,
                )
                formatted_comments.append(formatted_comment)

        return formatted_comments

    def _make_idempotency_marker(self, comment: Dict) -> str:
        import hashlib
        key = f"{comment.get('new_file_path')}:{comment.get('new_line')}:{comment.get('category')}:{comment.get('severity')}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    def _save_debug_hunks(self, hunks: List[Dict]):
        """Save hunks for debugging."""
        import json
        import os

        os.makedirs("debug", exist_ok=True)
        with open(
            f"debug/hunks_{self.provider_name.lower()}.json", "w", encoding="utf-8"
        ) as f:
            json.dump(hunks, f, ensure_ascii=False, indent=2)

    def _save_debug_files(self, mapped_comments: List, all_formatted_comments: List):
        """Save debug files."""
        import json
        import os

        os.makedirs("debug", exist_ok=True)

        provider_suffix = self.provider_name.lower()

        with open(f"debug/ai_review_comments_mapped_{provider_suffix}.json", "w") as f:
            json.dump(mapped_comments, f, indent=2)

        with open(
            f"debug/ai_review_comments_formatted_{provider_suffix}.json", "w"
        ) as f:
            json.dump(all_formatted_comments, f, indent=2)

    def _save_failed_gitlab_comments(
        self, pr_id: str, failed_comments: List[Dict]
    ) -> None:
        """Save failed GitLab comments to a debug file."""
        import json
        import os
        from datetime import datetime

        # Create debug directory if it doesn't exist
        os.makedirs("debug/gitlab_failures", exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"debug/gitlab_failures/failed_comments_pr_{pr_id}_{timestamp}.json"

        failed_data = {
            "timestamp": datetime.now().isoformat(),
            "pr_id": pr_id,
            "failed_count": len(failed_comments),
            "failed_comments": failed_comments,
        }

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(failed_data, f, ensure_ascii=False, indent=2)
            print(f"📝 Saved failed GitLab comments to: {filename}")
        except Exception as e:
            print(f"Failed to save GitLab comment failures: {e}")
