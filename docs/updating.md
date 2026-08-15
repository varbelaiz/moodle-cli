# Updating

Releases are git tags on this repo, not packages on an index — the name `moodle-cli` is
already taken on PyPI by an unrelated project, so an install always names this repo
directly rather than resolving through a package index. `moodle version --check` and
`moodle update` are the only commands here that make a network call outside a Moodle
campus: both talk to the GitHub Releases API for this repo, nothing else.

## `moodle version`

```
moodle version [--check] [--json]
```

| Option | Description |
| --- | --- |
| `--check` | Also ask GitHub whether a newer release exists. |
| `--json` | Emit JSON instead of plain text. |

Without `--check` this never reaches the network — it prints the version baked into the
install and returns. `--check` adds one call to GitHub's latest-release endpoint.

Example output:

```
moodle-cli 0.1.0
```

```
$ moodle version --check
moodle-cli 0.1.0
v0.2.0 is available. Run `moodle update`.
```

Example `--json` response:

```json
{
  "version": "0.1.0",
  "latest": "v0.2.0",
  "update_available": true
}
```

## `moodle update`

```
moodle update [--json]
```

| Option | Description |
| --- | --- |
| `--json` | Emit JSON instead of streaming the packaging tool's output. |

Checks the latest GitHub release and, if it is newer than what is installed, reinstalls
moodle-cli at that tag. Already up to date is a no-op — nothing is reinstalled and nothing
downloaded beyond the one release check.

What it does depends on where moodle is installed, the same as `moodle plugins install`.
From a source checkout it refuses and tells you to `git pull` instead — an editable
install already tracks whatever is on disk. Without uv on PATH it prints the command to
run yourself and stops.

**Extras and hand-injected packages are carried across.** A `uv tool install` reinstall
restates the currently installed plugin extras and anything added by hand with `--with`,
the same restatement `moodle plugins install`/`uninstall` do — only the version pin moves.

Example output:

```
Updated 0.1.0 -> v0.2.0.
```

Example `--json` response:

```json
{
  "action": "updated",
  "from": "0.1.0",
  "to": "v0.2.0",
  "environment": "uv-tool",
  "command": ["uv", "tool", "install", "--reinstall", "moodle-cli[anydoc] @ git+https://github.com/varbelaiz/moodle-cli@v0.2.0"],
  "output": ""
}
```
