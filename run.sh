#!/bin/sh
# Start Quote Vault from a terminal. Stop it with Ctrl+C.
# For everyday use, open "Quote Vault.app" instead (see launcher/build.sh).
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -m app.serve "$@"
