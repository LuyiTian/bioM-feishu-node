# Release Guide

Distribution: install direct from GitHub. No PyPI.

```bash
pip install "git+https://github.com/LuyiTian/bioM-feishu-node.git"
# Pin to a tag for production:
pip install "git+https://github.com/LuyiTian/bioM-feishu-node.git@v0.2.0"
```

Nodes running under `feishu-node-launcher` auto-upgrade to the latest
`vX.Y.Z` tag once per day. They will not pick up untagged main commits.

## Cutting a Release

1. Bump `version` in `pyproject.toml` (e.g. `0.2.1`).
2. Commit on `main` (PR + merge, or direct push if you own the repo).
3. Tag and push:

   ```bash
   git tag v0.2.1
   git push origin v0.2.1
   ```

4. Done. Within 24 h every launcher-managed node will pip-install the new
   tag and respawn. To roll faster, run `/node upgrade` in any Feishu
   group you own (pushes an immediate upgrade signal to every online node
   you own).

## Tag Discipline

The launcher's tag-only safety check requires the form `vX.Y.Z` —
exactly three integer components, leading `v`. Tags like `v0.2`,
`v0.2.0-rc1`, `release-2026-05-13`, or `latest` are rejected and will
not be auto-installed.

## Rollback

Auto-upgrade is forward-only — it won't downgrade. If a release is bad:

1. Cut a new patch tag (`v0.2.2`) that reverts the offending commits.
2. Push the tag. Nodes pick it up within 24 h, or push them with
   `/node upgrade` from a Feishu group.

Yanking a tag does **not** roll nodes back, because their installed
version is already on disk; you must publish a higher tag.
