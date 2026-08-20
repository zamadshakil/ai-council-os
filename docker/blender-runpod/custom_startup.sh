#!/usr/bin/env bash
set -uo pipefail

mkdir -p /workspace/logs /workspace/render_jobs /workspace/.council-blender
agent_token="${BLENDER_AGENT_TOKEN:-}"
if [[ ${#agent_token} -lt 32 ]]; then
    echo "BLENDER_AGENT_TOKEN is missing or too short; production agent disabled." >> /workspace/logs/startup.log
    exec sleep infinity
fi

while true; do
    echo "$(date -u +%FT%TZ) starting Council OS Blender agent" >> /workspace/logs/startup.log
    /opt/council-agent/bin/python /opt/council/blender_listener.py \
        >> /workspace/logs/blender-agent.log 2>&1
    status=$?
    echo "$(date -u +%FT%TZ) agent exited ${status}; restarting in 5 seconds" >> /workspace/logs/startup.log
    sleep 5
done
