#!/bin/sh
# The box's entrypoint (plan step 1.0a). Runs as root, in this order: the egress list, the marker, then a drop to
# the user `node` with no capabilities and no-new-privs. Each step that fails stops the start: no session runs
# without the firewall or without the marker.
set -eu
share=/usr/local/share/agent-box
if [ "$(id -u)" != 0 ]; then
  echo "box: the entrypoint must start as root (it sets the firewall); no session starts" >&2
  exit 70
fi
if ! python3 "$share/firewall.py" --allowlist "$share/allowlist"; then
  echo "box: the firewall could not be set; no session starts" >&2
  exit 70
fi
if ! python3 "$share/marker.py"; then
  echo "box: the marker could not be written; no session starts" >&2
  exit 70
fi
export HOME=/home/node USER=node LOGNAME=node
exec setpriv --reuid=node --regid=node --init-groups --inh-caps=-all --bounding-set=-all --no-new-privs -- "$@"
