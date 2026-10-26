# Security Architecture

This directory contains documentation for ASTRA's security model.

## Principles

1. **Environment Variables**: No hardcoded secrets. Use `.env`.
2. **Tool Permissions**: ASTRA cannot execute high-risk commands without explicit approval.
3. **Data Isolation**: ASTRA operates on a specific local dataset; system-wide filesystem access must be explicitly granted.
