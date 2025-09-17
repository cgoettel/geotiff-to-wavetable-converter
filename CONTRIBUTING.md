# Contribution guide

If you would like to contribute to this repository, you are absolutely welcome to! It's nascent right now so I'll fill this out more as things move along. General contribution guidelines apply (e.g., be kind, rewind; document everything you do, write test cases, etc.).

We're doing everything here as native to GitLab as possible. That means that we're using the [issue tracker](https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/issues) and the milestones within GitLab, GitLab CI, and so on.

## Tests and pre-commit hooks

When contributing to this project, please ensure that you write tests for your changes and that all tests are passing before submitting a merge request.

### Running Tests

To run the tests, you first need to install the test dependencies:

```bash
uv pip install -e '.[test]'
```

Then, you can run the tests with the following command:

```bash
uv run pytest
```

### Running Pre-commit Hooks

This project uses pre-commit to enforce code style and quality. To run the hooks, you first need to install the test dependencies:

```bash
uv pip install -e '.[test]'
```

Then, you can run the hooks on all files with the following command:

```bash
uv run pre-commit run --all-files
```
