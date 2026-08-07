# Plugins

CLI only — a plugin's own commands and MCP tools are documented by that plugin.

A plugin is a separate package that adds a command group and MCP tools. It cannot wrap,
replace or modify anything moodle-cli already exposes, and that restriction is the point:
an installed package able to change what `course download` does would make this tool's
behavior unreadable from its own source. Adding is enough for the cases that come up —
a campus with a recordings platform, a conversion step someone wants — and it keeps every
command auditable.

Discovery costs one scan of the installed packages, and only what is installed can run.
Nothing ships enabled.

## `moodle plugins list`

```
moodle plugins list [--json]
```

| Option | Description |
| --- | --- |
| `--json` | Emit JSON instead of a table. |

Lists the official plugins for this release, plus any third-party plugin installed here.
`status` is `installed`, `available`, or `error` for one that is installed but was
rejected; the reason for a rejection is printed to stderr under the table. `adds` names the
command group and MCP tools the plugin contributes, which is knowable only once it has been
imported.

Third-party plugins are listed even though this command cannot install or remove them. A
command group appearing in `moodle --help` from nowhere, or a plugin skipped for a reason
nobody can read, is exactly what this command is for.

**`list` never reaches the network.** The catalog comes from the extras this release
declares and the packages present on this machine, so the command works offline and tells
no package index what you are looking at. That is also why an `available` plugin has no
description: the summary lives in that package's own metadata, which is not here yet.

Example output:

```
                                            3 plugins
┏━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ name    ┃ source      ┃ status    ┃ version ┃ adds                                       ┃ description     ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ anydoc  │ official    │ installed │   0.1.0 │ anydoc, anydoc_convert_to_markdown,       │ Convert docs.   │
│         │             │           │         │ anydoc_get_markdown                       │                 │
│ panopto │ official    │ available │       - │ -                                          │ -               │
│ demo    │ third-party │ installed │   0.1.0 │ demo                                       │ A local plugin. │
└─────────┴─────────────┴───────────┴─────────┴────────────────────────────────────────────┴─────────────────┘
Install one with `moodle plugins install NAME`.
```

Example `--json` response:

```json
[
  {
    "name": "anydoc",
    "distribution": "moodle-cli-anydoc",
    "official": true,
    "status": "installed",
    "version": "0.1.0",
    "summary": "Convert course documents to markdown.",
    "command_group": "anydoc",
    "mcp_tools": ["anydoc_convert_to_markdown", "anydoc_get_markdown"],
    "problem": null
  }
]
```

## `moodle plugins install`

```
moodle plugins install NAME [--json]
```

| Option | Description |
| --- | --- |
| `--json` | Emit JSON instead of streaming the packaging tool's output. |

Installs an official plugin into the environment moodle itself is running from, which is
what removes the question of which virtual environment a plain `pip install` would land in.
`NAME` must be an official plugin from `plugins list`; this installs neither arbitrary
packages nor the third-party plugins it lists, which stay yours to manage.

What it does depends on where moodle is installed. From a source checkout it refuses and
tells you to use `uv sync --extra NAME`, because installing would replace your editable
install with a built one. Without uv on PATH it prints the command to run and stops.

**Installing rebuilds the whole tool environment.** Extras and packages injected with
`--with` belong to the environment rather than to a package, and `uv tool install` replaces
that set rather than adding to it. So the command is reconstructed from the current state
every time and anything you injected by hand is restated. If that set cannot be read, the
install stops instead of proceeding — dropping someone's packages silently is worse than
refusing.

**The new commands appear on the next invocation.** The running process has already built
its command tree.

Example output:

```
Installed anydoc. Its commands appear on the next run.
```

## `moodle plugins uninstall`

```
moodle plugins uninstall NAME [--json]
```

Removes a plugin, rebuilding the environment the same way. In a plain virtual environment
the extra still declares the dependency, so installing `moodle-cli[NAME]` again brings it
back.

## `MOODLE_NO_PLUGINS`

Set it to any non-empty value to skip discovery entirely. It is the way out when a plugin
breaks the command line itself, and it is what the test suite uses so an installed plugin
cannot change what the tests prove.
