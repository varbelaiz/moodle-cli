# Announcements

CLI: `moodle course announcements`
MCP: `get_course_announcements`

```
moodle course announcements COURSE [--json]
```

MCP parameter: `course`, optional — omit it to check every enrolled course, dashboard-
hidden ones included.

Lists posts from a course's news forum, newest first, with subject, author, timestamp and
pinned status. Only a forum Moodle marks as `"news"` carries announcements; a course's
regular discussion forums are not included, and a course without a news forum returns
nothing.

Posts are HTML on the wire and are surfaced as plain text, one line per paragraph or list
item. Both surfaces carry a `posted_at` timestamp that keeps the time of day, which is
what tells two same-day posts apart.
