#!/bin/bash
set -u
cd -- "$(dirname -- "$0")" || exit 1
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)' >/dev/null 2>&1; then
    "$candidate" scripts/bootstrap.py "$@"
    result=$?
    if [ "$result" -ne 0 ] && [ "$result" -ne 130 ]; then
      read -r -p "Press Return to close…" _
    fi
    exit "$result"
  fi
done
printf '%s\n' 'Install Python 3.11, 3.12, or 3.13 from https://www.python.org/downloads/macos/ then launch Frameva again.'
read -r -p "Press Return to close…" _
exit 1
