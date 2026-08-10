# Tool Architecture

This directory contains documentation for ASTRA's tool execution system.

## Principles

1. **Security First**: Tools operate in sandboxes where appropriate and declare explicit permissions.
2. **Schema Driven**: Tools define strict input schemas.
3. **No Blind Execution**: High-risk tools (file deletion, sending email) require explicit user approval.

For code, see `backend/app/tools/`.
