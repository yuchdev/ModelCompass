# Hooks Reference

| Hook | Trigger | Description |
|------|---------|-------------|
| `dep_audit` | PostToolUse: Write|Edit|MultiEdit | PostToolUse / Write|Edit on dependency manifests - dependency audit trigger. |
| `doc_link_check` | PostToolUse: Write|Edit|MultiEdit; Stop | PostToolUse (Write|Edit|MultiEdit) + Stop: documentation reference integrity. |
| `github_audit` | PostToolUse: mcp__github__.* | PostToolUse / mcp__github__* - audit trail for GitHub MCP calls. |
| `guard_bash` | PreToolUse: Bash | PreToolUse / Bash guard. |
| `post_edit_format` | PostToolUse: Write|Edit|MultiEdit | PostToolUse / Write|Edit|MultiEdit. |
| `run_tests` | Stop | Stop hook - gate the end of a session on lint + tests, unconditionally. |
| `secret_scan` | PreToolUse: Write|Edit|MultiEdit | Secret scanner - dual mode. |
| `session_start` | SessionStart | SessionStart hook - seed the session with live repo context. |
| `style_fixes` | PostToolUse: Write|Edit|MultiEdit | Python style-fix codemod - dual mode, extensible rule list. |
