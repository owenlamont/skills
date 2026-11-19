# Skills

Engineering skills for coding agents, in the
[Agent Skills](https://agentskills.io/specification) format.

| Skill | Covers |
| --- | --- |
| `software-engineering` | Language-agnostic practice: verify by running, diagnose first, keep changes small |
| `docs` | Issue and PR bodies, review comments, commit messages, code comments |
| `pr-review` | End-to-end review of a PR or branch |
| `dry` | Finding deletable duplicated or hand-rolled Python |
| `python-async` | asyncio |
| `python-code-style` | Python style, typing, docstrings |
| `python-datetime` | Dates, times and timezones |
| `python-error-handling` | Exceptions |
| `python-libraries` | Preferred libraries over hand-rolled code |
| `python-lint-format` | prek, ruff, ty and friends |
| `python-pandas` | Pandas and Pandera |
| `python-pydantic` | Pydantic v2 models and settings |
| `python-pytest` | pytest |
| `python-uv-workflow` | uv dependencies and scripts |
| `rust-code-style` | Rust style |
| `rust-concurrency` | rayon, threads, channels, atomics |
| `rust-testing` | Rust tests and coverage |
| `sql-data-modelling` | SQL and schema design |
| `typescript` | TypeScript: tsconfig, types, linting, tests, VS Code extensions |

## Installing

With the GitHub CLI's `gh skill`, one skill per call:

```sh
gh skill install owenlamont/skills skills/<name> --agent <host> --scope user
```

`<host>` is `claude-code`, `codex`, `cursor`, `gemini-cli` and others; set it
explicitly, since the non-interactive default is `github-copilot`. Releases are tagged,
so `gh skill update --all` picks up new ones.

## Contributing

```sh
prek install --install-hooks
```

Git does not install hooks on clone, so run that once per clone. CI runs
`prek run --all-files` and `uv run pytest` as the `checks` job either way.
[AGENTS.md](AGENTS.md) has the layout and toolchain.

## License

MIT
