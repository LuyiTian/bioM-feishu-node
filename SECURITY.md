# Security Policy

## Reporting a Vulnerability

Please open a private security report through GitHub Security Advisories.
Do not post exploit details in public issues.

## Token Handling

- Gateway token and pairing token are credentials.
- Never commit credentials to git.
- Never post credentials in screenshots or logs.
- Local node token is stored at `~/.feishu-node/config.json`.

## Least Privilege

- Only grant project-specific directories via `--allow-dir`.
- Avoid granting full home/root/system directories.
- Use `--no-shell` when command execution is not required.

## Operational Hygiene

- Rotate leaked tokens immediately.
- Keep client updated to the latest release.
- Remove old nodes from admin panel when devices are decommissioned.
