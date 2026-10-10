# Security Policy

## Scope

This alpha project evaluates JSON observations locally or over MCP stdio. It is intended for controlled local testing, not multi-tenant SaaS deployment.

## Supported versions

Security fixes are applied to the latest 0.1.x release only.

## Reporting a vulnerability

Open a private security advisory on the GitHub repository if available, or contact the maintainers through the repository contact channel. Do not open a public issue for unfixed vulnerabilities that could be exploited.

## Design constraints

- No evaluation of untrusted code via `eval`/`exec`.
- Input sizes and nesting depth are bounded.
- MCP stdio should emit only protocol messages on stdout.
- Do not send production secrets into tool arguments or logs.

## Residual risks

Callers supply expected/actual observations. Incorrect adapters can mislabel outcomes. Treat release gates as advisory for pilot validation, not as a sole production control.
