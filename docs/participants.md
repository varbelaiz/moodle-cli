# Course participants

CLI: `moodle course participants`
MCP: `list_participants`

```
moodle course participants COURSE [--role SHORTNAME] [--emails] [--json]
```

| Option | Description |
| --- | --- |
| `--role SHORTNAME` | Filter by role, e.g. `student`, `editingteacher`. |
| `--emails` | Include email addresses. Hidden by default. |
| `--json` | JSON output. |

MCP parameters: `course`, `role`, `include_emails` (default `false`).

Lists the people enrolled in a course: name, roles, and last course access. Email
addresses are withheld unless explicitly requested — via `--emails` on the CLI or
`include_emails` on MCP — in the table and in JSON alike.
