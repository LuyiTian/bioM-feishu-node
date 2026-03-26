# Release Guide

Current default distribution is GitHub direct install:

```bash
pip install "git+https://github.com/LuyiTian/bioM-feishu-node.git"
```

This document explains optional PyPI publishing so users can install with:

```bash
pip install biom-feishu-node
```

## One-time Setup (You need to do this manually)

1. Push current branch to GitHub.
2. Create project `biom-feishu-node` on PyPI (https://pypi.org/manage/projects/).
3. In PyPI project settings, add **Trusted Publisher**:
   - Owner: `LuyiTian`
   - Repository: `bioM-feishu-node`
   - Workflow name: `publish.yml`
   - Environment: leave empty
4. Ensure GitHub Actions are enabled for the repository.

After this, no API token is needed in GitHub Secrets.

## Every Release

1. Bump version in `pyproject.toml` (e.g. `0.1.1`).
2. Commit and push to `main`.
3. Create and push a matching git tag:

```bash
git tag v0.1.1
git push origin v0.1.1
```

4. GitHub Action `Publish` will run automatically and upload to PyPI.

## Safety Checks in CI

The publish workflow enforces:
- build succeeds (`python -m build`)
- metadata check (`twine check dist/*`)
- tag/version match (`vX.Y.Z` must equal `project.version`)

## Verify Published Package

```bash
python -m venv /tmp/venv-check
source /tmp/venv-check/bin/activate
pip install --upgrade pip
pip install biom-feishu-node
feishu-node --help
```

## Rollback Strategy

PyPI does not allow overwriting an existing version. If release is bad:
- yanks are possible, or
- publish a new patch version (recommended): `0.1.2`
