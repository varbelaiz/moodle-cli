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
`include_emails` on MCP — in the table and in JSON alike: the `email` key is left out of
the response entirely rather than sent as `null`.

Example `--json` response with `--emails`:

```json
[
  {
    "id": 55,
    "fullname": "Jane Doe",
    "firstname": "Jane",
    "lastname": "Doe",
    "email": "jane.doe@example.edu",
    "roles": [
      {"roleid": 5, "name": "Student", "shortname": "student"}
    ],
    "lastcourseaccess": 1718000000
  }
]
```

Example `list_participants` response with `include_emails: true` — roles flattened to
shortnames, the access timestamp as a date:

```json
[
  {
    "id": 55,
    "fullname": "Jane Doe",
    "roles": ["student"],
    "last_course_access": "2024-06-10",
    "email": "jane.doe@example.edu"
  }
]
```
