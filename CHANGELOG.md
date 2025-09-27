# CHANGELOG

## [0.0.4]

- Implemented robust background submission system using asyncio for parallel processing
- Added proper shutdown mechanism with asyncio.Event for clean process termination
- Enhanced error handling with comprehensive logging of failed comments
- Improved debug logging with detailed submission tracking and statistics
- Added support for extensible LLM provider architecture via factory pattern
- Fixed CLI command exit issue when processing is complete

## [0.0.3]

- Allow to post comment to Gitlab, Github and Azure Devops after AI reviewed

## [0.0.2]

- Add deployment for TestPyPI, allow run ai-pr-reviewer CLI
- Refine README.md with support for Gitlab, Github and Azure Devops

## [0.0.1]

- Initial package with support for code review using Gemini API on Gitlab and Github
