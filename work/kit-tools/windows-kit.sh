#!/bin/sh
set -eu

# Resolve the checkout before invoking Windows programs, also when reached via ~/herdr_tools.
cd -P "$(dirname "$0")/../.."
local_app_data=$(/mnt/c/Windows/System32/cmd.exe /d /c 'echo %LOCALAPPDATA%' | tr -d '\r')
programs="$(wslpath -u "$local_app_data")/Programs"
launcher="$programs/Python/Launcher/py.exe"
core="$programs/herdr-core/hc.exe"
for program in "$launcher" "$core"; do
    if [ ! -f "$program" ]; then
        echo "Windows executable missing: $program" >&2
        exit 1
    fi
done
operation=${1:-diagnose}
if [ "$#" -gt 0 ]; then shift; fi
case "$operation" in
    install) python3 -B work/kit-tools/stage.py ;;
    diagnose) ;;
    *) echo "Usage: sh work/kit-tools/windows-kit.sh {install|diagnose} [kit options]" >&2; exit 2 ;;
esac

# Herdr's native checks need the desktop session even when the SSH server is a WSL service.
exec "$core" exec --timeout 300 "$(wslpath -w "$launcher")" -3 -B -X utf8 \
    "$(wslpath -w "$PWD/work/herdr-mod-kit/kit.py")" "$operation" "$@"
