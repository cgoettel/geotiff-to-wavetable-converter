# Contribution guide

If you would like to contribute to this repository, you are absolutely welcome to! It's nascent right now so I'll fill this out more as things move along. General contribution guidelines apply (e.g., be kind, rewind; document everything you do, write test cases, etc.).

We're doing everything here as native to GitLab as possible. That means that we're using the [issue tracker](https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/issues) and the milestones within GitLab, GitLab CI, and so on.

## Development

Most of what you're going to read in this section is covered by the [Makefile](Makefile). You can use that to help ease the process.

### Local development with uv

I recommend doing your development work in a virtual environment using `uv`.

Prerequisites:

- Python 3.x installed and in PATH.
- `uv` installed.

Step-by-step instructions:

1. Install the `uv` CLI (one-time):

   ```bash
   python -m pip install uv
   ```

2. Verify `uv` is available:

   ```bash
   uv --version
   ```

3. From your project root (the directory that contains `src/`), create a virtual environment directory (example name: `.venv`).

   ```bash
   uv venv
   ```

4. Activate the virtual environment:

   - macOS / Linux:

     ```bash
     source .venv/bin/activate
     ```

   - Windows (PowerShell):

     ```bash
     .\.venv\Scripts\Activate.ps1
     ```

   - Windows (cmd.exe):

     ```bash
     .\.venv\Scripts\activate.bat
     ```

5. Install the project. From the project root, run:

   ```bash
   uv sync
   ```

6. Deactivate when finished:

   ```bash
   deactivate
   ```

> 💡 **Tips and notes**
>
> - Always run the commands from the project root, not src/.
> - `uv sync` installs the project in editable mode, so changes in `src/` are immediately available.
> - For CI or reproducible builds, prefer explicit commands (create env, activate, install dependencies) and pin dependency versions in a lockfile or requirements file.

## Tests and pre-commit hooks

When contributing to this project, please ensure that you write tests for your changes and that all tests are passing before submitting a merge request.

To run the tests or pre-commit hooks, you need to install the test dependencies and install pre-commit:

```bash
uv sync --extra test
uv run pre-commit install
```

### Running tests

You can run the tests with the following command:

```bash
uv run pytest
```

`tests/test_integration.py` drives the whole command line against synthetic GeoTIFFs and checks the `.wt` bytes against the format spec. It can't judge how a wavetable sounds, so before a release also work through [docs/manual-validation.md](docs/manual-validation.md).

### Running pre-commit hooks

This project uses pre-commit to enforce code style and quality. You can run the hooks on all files with the following command:

```bash
uv run pre-commit run --all-files
```

## Building and uploading to PyPi

### Building the package

Build the package with uv:

```bash
uv build
```

This creates two files in a new dist/ directory:

- A .tar.gz source distribution
- A .whl wheel file

### Testing the package locally

Create a test environment and install from your built package:

```bash
cd /tmp
uv venv test-geotiff-env
source test-geotiff-env/bin/activate
```

Then, install your package from the wheel file

```bash
uv pip install ~/git/geotiff-to-wavetable-converter/dist/geotiff_to_wavetable-*-py3-none-any.whl
```

We can now test that the CLI functions properly:

```bash
geotiff-to-wavetable --help
```

The first run will be slow. This is expected.

If --help shows the usage information, the package is working! You can test further functionality or call it quits, deactivate, and clean up:

```bash
deactivate
rm -rf test-geotiff-env
```

### Releasing to PyPI

Releases publish automatically from GitLab CI. Pushing a version tag runs the `publish_to_pypi` job, which checks that the tag matches the version in `pyproject.toml`, runs the tests, builds, and uploads. There's no API token to manage: PyPI trusts this repository's CI through a [trusted publisher](https://docs.pypi.org/trusted-publishers/).

1. Bump the version and add a section to `CHANGELOG.md`:

   ```bash
   uv version --bump minor   # or patch / major
   ```

2. Merge that change to `main`, then tag the merge and push the tag:

   ```bash
   git switch main && git pull
   git tag -a "v$(uv version --short)" -m "v$(uv version --short)"
   git push origin "v$(uv version --short)"
   ```

3. Watch the tag's pipeline, then confirm the release at <https://pypi.org/project/geotiff-to-wavetable/>.

PyPI never lets a version number be reused, even after a release is deleted, so fix a bad release by publishing the next patch version.

#### One-time setup: the trusted publisher

On PyPI, open **geotiff-to-wavetable → Manage → Publishing → Add a new publisher → GitLab** and enter:

| Field                        | Value                            |
| ---------------------------- | -------------------------------- |
| Namespace                    | `colby.goettel`                  |
| Project name                 | `geotiff-to-wavetable-converter` |
| Top-level pipeline file path | `.gitlab-ci.yml`                 |
| Environment name             | `pypi`                           |
