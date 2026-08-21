#!/usr/bin/env bash
set -uo pipefail

mkdir -p /workspace/logs /workspace/render_jobs /workspace/.council-blender/samples \
    /workspace/.council-flamenco
sample_target=/workspace/.council-blender/samples/Blender-282.blend
if [[ ! -s "$sample_target" ]]; then
    cp /opt/council/samples/Blender-282.blend "$sample_target"
fi
gpu_sample_target=/workspace/.council-blender/samples/BMW27_GPU.blend
if [[ ! -s "$gpu_sample_target" ]]; then
    cp /opt/council/samples/BMW27_GPU.blend "$gpu_sample_target"
fi
agent_token="${BLENDER_AGENT_TOKEN:-}"
if [[ ${#agent_token} -lt 32 ]]; then
    echo "BLENDER_AGENT_TOKEN is missing or too short; production agent disabled." >> /workspace/logs/startup.log
    # Kasm invokes this file as a startup hook. The hook must return so the
    # desktop and KasmVNC server can continue starting even when the optional
    # Council OS agent is not configured.
else
    coordinator_url="${FLAMENCO_COORDINATOR_AGENT_URL:-}"
    if [[ -n "$coordinator_url" ]]; then
        coordinator_token="${FLAMENCO_COORDINATOR_AGENT_TOKEN:-}"
        if [[ ${#coordinator_token} -lt 32 ]]; then
            echo "FLAMENCO_COORDINATOR_AGENT_TOKEN is missing or too short; remote Worker gateway disabled." \
                >> /workspace/logs/startup.log
        else
            # Remote Flamenco Workers cannot add Council OS authentication to
            # their requests. This loopback-only gateway adds the coordinator's
            # distinct token; port 8181 is not exposed.
            nohup bash -c '
                exec 9>/workspace/.council-flamenco/gateway.lock
                flock -n 9 || exit 0
                while true; do
                    /opt/council-agent/bin/python /opt/council/flamenco_gateway.py \
                        >> /workspace/logs/flamenco-gateway.log 2>&1
                    sleep 5
                done
            ' </dev/null >> /workspace/logs/flamenco-gateway-supervisor.log 2>&1 &
            echo "$!" > /workspace/.council-flamenco/gateway-supervisor.pid
        fi
    fi

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

    nohup bash -c '
        exec 9>/workspace/.council-blender/desktop-watchdog.lock
        flock -n 9 || exit 0
        exec /opt/council-agent/bin/python /opt/council/desktop_control.py
    ' </dev/null >> /workspace/logs/desktop-watchdog-supervisor.log 2>&1 &
    echo "$!" > /workspace/.council-blender/desktop-watchdog.pid
    echo "$(date -u +%FT%TZ) Council OS Blender agent supervisor started in background" \
        >> /workspace/logs/startup.log
fi
