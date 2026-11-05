## Summary

What problem does this PR solve, and why is this the smallest safe change?

## Change classification

- [ ] Bug fix
- [ ] New functionality
- [ ] Security hardening
- [ ] Documentation / tests / maintenance
- [ ] Breaking change (explain migration below)

## Verification

- [ ] `python -m pytest tests/ --cov=gotify_notify --cov-fail-under=95`
- [ ] `python -m ruff check gotify_notify tests`
- [ ] `python scripts/sync_version.py --check`
- [ ] Companion utility tests, if affected
- [ ] No real credentials, tokens, or private hostnames appear in this PR

**Tests added or changed:**

**Compatibility / deployment considerations:**

## Security and release considerations

Describe any changes to authentication, network destinations, GitHub Actions permissions, third-party dependencies, or release behavior. Do not include exploitable vulnerability details in a public PR before coordinating disclosure.

## Related issues

Closes # (if applicable)
