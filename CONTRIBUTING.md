# Contributing

Issues and pull requests are welcome.

Before you open a pull request:

1. Run `python -m pytest -q`. The tests need no keys and no network.
2. Run `hermes plugins validate ./ --install-deps` and `hermes plugins doctor ./ --ci`.
3. Keep changes to the policy, receipts and hooks covered by a test.

Report security issues to security@arcade.dev, not in a public issue (see SECURITY.md).

By contributing, you agree that your contribution is licensed under the Apache License 2.0.
