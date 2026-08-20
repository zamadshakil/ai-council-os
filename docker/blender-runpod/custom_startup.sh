#!/usr/bin/env bash
set -uo pipefail

mkdir -p /workspace/logs /workspace/render_jobs /workspace/.council-blender/samples
sample_target=/workspace/.council-blender/samples/Blender-282.blend
if [[ ! -s "$sample_target" ]]; then
    cp /opt/council/samples/Blender-282.blend "$sample_target"
fi
agent_token="${BLENDER_AGENT_TOKEN:-}"
if [[ ${#agent_token} -lt 32 ]]; then
    echo "BLENDER_AGENT_TOKEN is missing or too short; production agent disabled." >> /workspace/logs/startup.log
    # Kasm invokes this file as a startup hook. The hook must return so the
    # desktop and KasmVNC server can continue starting even when the optional
    # Council OS agent is not configured.
else
    # The custom startup hook is on Kasm's critical path. Run the restart loop
    # in the background and return immediately; keeping it in the foreground
    # prevents KasmVNC from ever binding port 6901. flock ensures a repeated
    # hook invocation cannot create a second agent supervisor.
    nohup bash -c '
        exec 9>/workspace/.council-blender/agent.lock
        flock -n 9 || exit 0
        while true; do
            echo "$(date -u +%FT%TZ) starting Council OS Blender agent" >> /workspace/logs/startup.log
            /opt/council-agent/bin/python /opt/council/blender_listener.py \
                >> /workspace/logs/blender-agent.log 2>&1
            status=$?
            echo "$(date -u +%FT%TZ) agent exited ${status}; restarting in 5 seconds" >> /workspace/logs/startup.log
            sleep 5
        done
    ' </dev/null >> /workspace/logs/agent-supervisor.log 2>&1 &

    echo "$!" > /workspace/.council-blender/agent-supervisor.pid
    echo "$(date -u +%FT%TZ) Council OS Blender agent supervisor started in background" \
        >> /workspace/logs/startup.log
fi
