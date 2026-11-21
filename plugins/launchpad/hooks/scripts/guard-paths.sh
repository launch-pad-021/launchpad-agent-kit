#!/bin/sh
# Claude treats ordinary nonzero exit codes as non-blocking hook errors.
hook=${0##*/}
runtime=$(dirname "$0")/hook.py
if [ -r "$runtime" ] && command -v python3 >/dev/null 2>&1; then
    python3 -I -B "$runtime" "$hook"
    status=$?
    case $status in 0) exit 0;; 20) exit 2;; esac
fi
case $hook in
    session-start.sh) echo '{"continue":false,"stopReason":"Launchpad hook runtime failed."}';;
    stop-checks.sh) echo '{"decision":"block","reason":"Launchpad hook runtime failed."}';;
    *) echo 'Launchpad guard runtime failed.' >&2; exit 2;;
esac
