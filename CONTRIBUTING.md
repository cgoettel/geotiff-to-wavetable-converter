# Contribution guide

If you would like to contribute to this repository, you are absolutely welcome to! It's nascent right now so I'll fill this out more as things move along. General contribution guidelines apply (e.g., be kind, rewind; document everything you do, write test cases, etc.).

We're doing everything here as native to GitLab as possible. That means that we're using the [issue tracker](https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/issues) and the milestones within GitLab, GitLab CI, and so on.

## Development

### Local development with uv

I recommend doing your development work in a virtual environment using `uv`.

Prerequisites:

- Python 3.x installed and in PATH.
- `uv` installed.

Step-by-step instructions:

1. Install the `uv` CLI (one-time):
     python -m pip install uv
1. Verify `uv` is available:
     uv --version
1. From your project root (the directory that contains `src/`), create a virtual environment directory (example name: `.venv`).
     uv venv
1. Activate the virtual environment:
     - macOS / Linux:
             source .venv/bin/activate
     - Windows (PowerShell):
             .\.venv\Scripts\Activate.ps1
     - Windows (cmd.exe):
             .\.venv\Scripts\activate.bat
1. Install the project. From the project root, run:
     uv sync
1. Deactivate when finished:
     deactivate

Tips and notes:

- Always run the commands from the project root, not src/.
- Prefer editable install (`pip install -e .`) for development so changes in `src/` are immediately available.
- For CI or reproducible builds, prefer explicit commands (create env, activate, install dependencies) and pin dependency versions in a lockfile or requirements file.
"""

## Tests and pre-commit hooks

When contributing to this project, please ensure that you write tests for your changes and that all tests are passing before submitting a merge request.

To run the tests or pre-commit hooks, you need to install the test dependencies and install pre-commit:

```bash
uv pip install -e '.[test]'
uv run pre-commit install
```

### Running tests

You can run the tests with the following command:

```bash
uv run pytest
```

### Running pre-commit hooks

This project uses pre-commit to enforce code style and quality. You can run the hooks on all files with the following command:

```bash
uv run pre-commit run --all-files
```
