import re
from typing import Dict, List, Optional, Tuple


class LineNumberMapper:
    """Handles mapping AI comments to correct absolute line numbers."""

    @staticmethod
    def map_comments_to_absolute_lines(
        ai_comments: List[Dict], hunks: List[Dict]
    ) -> List[Dict]:
        """Map AI-generated comments to correct absolute line numbers."""
        mapped_comments = []

        for comment in ai_comments:
            hunk_index = comment.get("hunk_index", 0)

            if hunk_index < len(hunks):
                hunk = hunks[hunk_index]
                header = hunk.get("hunk_header", "")

                # Extract new file starting line from header; support '@@ -a,b +c,d @@' and '@@ -a +c @@'
                match = re.search(r"@@\s*-\d+(?:,\d+)?\s*\+(\d+)(?:,(\d+))?\s*@@", header)

                if match:
                    new_start_line = int(match.group(1))
                    processed_lines = LineNumberMapper._normalize_hunk_lines(
                        hunk.get("hunk_lines", [])
                    )
                    line_to_diff_map = LineNumberMapper._build_new_line_to_diff_map(
                        processed_lines, new_start_line
                    )

                    mapped_comment = comment.copy()

                    absolute_line, diff_position = (
                        LineNumberMapper._map_ai_line_to_positions(
                            processed_lines,
                            new_start_line,
                            comment.get("new_line", 1),
                            comment.get("suggestion", ""),
                            comment.get("rationale", ""),
                        )
                    )

                    mapped_comment["new_line"] = absolute_line
                    mapped_comment["original_ai_line"] = comment.get("new_line")
                    mapped_comment["github_position"] = diff_position or line_to_diff_map.get(absolute_line)
                    mapped_comment["github_start_position"] = (
                        mapped_comment["github_position"]
                    )

                    end_line_ai = comment.get("end_line")
                    if end_line_ai:
                        end_absolute_line, end_diff_position = (
                            LineNumberMapper._map_ai_line_to_positions(
                                processed_lines,
                                new_start_line,
                                end_line_ai,
                                comment.get("suggestion", ""),
                                comment.get("rationale", ""),
                            )
                        )
                        mapped_comment["end_line"] = end_absolute_line
                        mapped_comment["github_end_position"] = (
                            end_diff_position
                            or line_to_diff_map.get(end_absolute_line)
                        )
                    else:
                        mapped_comment["github_end_position"] = mapped_comment[
                            "github_position"
                        ]

                    mapped_comments.append(mapped_comment)
                else:
                    comment["warning"] = (
                        "Could not parse hunk header for line calculation"
                    )
                    mapped_comments.append(comment)
            else:
                comment["warning"] = f"Invalid hunk_index: {hunk_index}"
                mapped_comments.append(comment)

        return mapped_comments

    @staticmethod
    def _normalize_hunk_lines(lines: List[Dict]) -> List[Dict]:
        processed_lines = []
        for line in lines:
            if isinstance(line, str):
                if line.startswith("+"):
                    processed_lines.append({"type": "+", "content": line[1:]})
                elif line.startswith("-"):
                    processed_lines.append({"type": "-", "content": line[1:]})
                else:
                    processed_lines.append({"type": " ", "content": line})
            else:
                processed_lines.append(line)
        return processed_lines

    @staticmethod
    def _build_new_line_to_diff_map(
        processed_lines: List[Dict], new_start_line: int
    ) -> Dict[int, int]:
        mapping: Dict[int, int] = {}
        current_new_line = new_start_line
        diff_index = 0
        for line_data in processed_lines:
            diff_index += 1
            if line_data.get("type", " ") in ["+", " "]:
                mapping[current_new_line] = diff_index
                current_new_line += 1
        return mapping

    @staticmethod
    def _map_ai_line_to_positions(
        processed_lines: List[Dict],
        new_start_line: int,
        ai_line_number: Optional[int],
        suggestion_text: str,
        rationale_text: str,
    ) -> Tuple[int, Optional[int]]:
        if ai_line_number is None or ai_line_number <= 0:
            ai_line_number = 1

        current_new_line = new_start_line
        line_count = 0
        diff_index = 0
        absolute_line = None
        diff_position = None

        for line_data in processed_lines:
            diff_index += 1
            line_type = line_data.get("type", " ")

            if line_type in ["+", " "]:
                line_count += 1
                if line_count == ai_line_number and absolute_line is None:
                    absolute_line = current_new_line
                    diff_position = diff_index
                current_new_line += 1

        if absolute_line is not None:
            return absolute_line, diff_position

        fallback_line, fallback_diff = LineNumberMapper._content_based_matching(
            processed_lines, new_start_line, suggestion_text, rationale_text
        )
        return fallback_line, fallback_diff

    @staticmethod
    def _content_based_matching(
        processed_lines: List[Dict],
        new_start_line: int,
        suggestion_text: str,
        rationale_text: str,
    ) -> Tuple[int, Optional[int]]:
        """Fallback content-based matching when line number mapping fails."""
        current_new_line = new_start_line
        best_match_line = new_start_line
        best_match_score = 0
        best_match_diff_position = None
        diff_index = 0

        search_text = f"{suggestion_text} {rationale_text}".lower()

        for line_data in processed_lines:
            diff_index += 1
            line_type = line_data.get("type", " ")
            line_content = line_data.get("content", "")

            if line_type in ["+", " "]:
                if search_text and line_content:
                    line_lower = line_content.lower()
                    score = 0

                    for word in search_text.split():
                        if len(word) > 3 and word in line_lower:
                            score += 1

                    # Prefer added lines over context lines
                    if line_type == "+":
                        score += 0.5

                    if score > best_match_score:
                        best_match_score = score
                        best_match_line = current_new_line
                        best_match_diff_position = diff_index

                current_new_line += 1

        return best_match_line, best_match_diff_position
