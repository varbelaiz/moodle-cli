# Authentication

CLI only — there is no MCP equivalent, since an agent talks over a token that's already
in place.

## `moodle auth login`

```
moodle auth login [--url URL] [--username, -u USERNAME]
```

| Option | Description |
| --- | --- |
| `--url` | Campus base URL. Falls back to `MOODLE_URL`, then the saved URL, then a prompt. |
| `--username`, `-u` | Campus username. Prompted for if omitted. |

Mints a web-service token and stores it in the system keyring. The password is always
prompted for, never taken as an argument — that would leave it in shell history. Once the
token is stored, `MOODLE_PASS` can be removed from `.env`.

The campus URL is saved only once the campus has confirmed the new token, so a mistyped URL
is never kept. It lives in the per-user config directory
(`~/Library/Application Support/moodle-cli` on macOS, `%APPDATA%\moodle-cli` on Windows,
`$XDG_CONFIG_HOME/moodle-cli` or `~/.config/moodle-cli` elsewhere), and every later command,
including the MCP server, reads it when `MOODLE_URL` is unset. Each login replaces it, so it
always names the campus the stored token belongs to.

Example output:

```
Logged in as Jane Doe (id 42)
  site: Example University  (4.4.1)
  token stored in the system keyring
```

## `moodle auth status`

```
moodle auth status
```

Shows whether a usable token exists and who it belongs to: full name, user id, site name,
number of web-service functions available, and whether file downloads are allowed.

Example output:

```
Authenticated as Jane Doe (id 42)
  site: Example University
  functions available: 187
  file downloads allowed: True
```

## `moodle auth logout`

```
moodle auth logout
```

Deletes the stored token from the keyring. The saved campus URL stays, so logging back in
needs no `--url`.

Example output:

```
Token deleted from the keyring.
```
