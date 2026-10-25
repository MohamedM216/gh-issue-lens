# Contributing to gh-issue-lens

First off, thank you for considering contributing to `gh-issue-lens`! It's people like you that make open-source software such a great community. 

This document outlines the process for setting up your development environment, making changes, and submitting them. It also includes the release process for maintainers.

## Table of Contents

- [Reporting Bugs](#reporting-bugs)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Development Setup](#development-setup)
- [Testing & Verification](#testing--verification)
- [Code Style & Linting](#code-style--linting)
- [License](#license)

## Reporting Bugs

If you find a bug in the source code, you can help us by submitting an issue to our GitHub Repository. Even better, you can submit a Pull Request with a fix!

Before you submit an issue, please search the repository's existing issues to ensure the bug hasn't already been reported.

When filing a bug, please include:

- **A clear and descriptive title.**

- **Steps to reproduce the behavior** (include the exact command you ran).

- **Expected vs. actual behavior.**

- **Your environment details** (Python version, OS, and `gh-issue-lens` version).

- **Any relevant error logs or output.**

## Submitting a Pull Request

1. Create a new branch for your feature or bugfix: `git checkout -b feature-name`
2. Commit your changes with descriptive messages.
3. Push the branch to your fork: `git push origin feature-name`
4. Open a Pull Request against the `master` branch of the `gh-issue-lens` repository.
5. In your PR description, briefly explain what you changed, why, and how you tested it.

## Development Setup

To start contributing, you'll need to fork the repository and set up a local development environment. 

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/gh-issue-lens.git
   cd gh-issue-lens
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
   *(To exit the virtual environment later, simply run `deactivate`)*

3. **Install the package in editable mode with development dependencies:**
   ```bash
   pip install -e .[dev]
   ```
   *(This ensures you have testing and linting tools like `pytest`, `ruff`, `build`, and `twine` installed).*

## Testing & Verification

Before submitting your changes, please ensure that everything works correctly.

1. **Run the automated tests:**
   ```bash
   pytest
   ```

2. **Verify your feature manually:**
   After making changes, you can verify the CLI tool works as expected by running it directly from your activated virtual environment. 
   
   Here is a standard test command against a large repository (requires `GITHUB_TOKEN` to be exported):
   ```bash
   export GITHUB_TOKEN="your_personal_access_token"
   gh-issue-lens kubernetes kubernetes -d 20 --exclude-open-prs
   ```

## Code Style & Linting

We use `ruff` to maintain a consistent code style and catch potential errors. 

1. **Auto-format and fix linting issues:**
   You can use the provided bash script which handles tab/space indentation, lint fixing, and formatting all at once:
   ```bash
   chmod +x format.sh
   ./format.sh
   ```

2. **Manual formatting (Alternative):**
   If you prefer to run `ruff` manually:
   ```bash
   ruff format .
   ruff check --fix .
   ```

Please ensure your code passes all formatting checks before pushing your branch.

## License

By contributing to `gh-issue-lens`, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).

## Thank You!

Thank you once again for your time, effort, and interest in improving `gh-issue-lens`. Every contribution, no matter how small, is deeply appreciated and helps make this tool better for everyone in the open-source community.

*Happy hacking!*
