"""
runpod_manager.py — RunPod Pod Control & API Integration

Allows AI Council OS to programmatically:
1. Start (podStart) and Pause/Stop (podStop) RunPod GPU pods
2. Query pod status, runtime, IP, and GPU metrics
3. Create pods from custom templates on-demand
4. Prevent idle billing by auto-stopping pods after render completion

Uses RunPod GraphQL API with httpx for fast, async execution.
"""

from __future__ import annotations

import os
import httpx
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"


def _get_api_key(override_key: Optional[str] = None) -> str:
    key = override_key or os.getenv("RUNPOD_API_KEY", "")
    if not key:
        raise ValueError(
            "RUNPOD_API_KEY is not set. Please set RUNPOD_API_KEY in your .env or pass it as an argument."
        )
    return key.strip()


async def execute_graphql(query_or_mutation: str, variables: Optional[dict] = None, api_key: Optional[str] = None) -> dict:
    """Execute a GraphQL query or mutation against the RunPod API."""
    key = _get_api_key(api_key)
    url = f"{RUNPOD_GRAPHQL_URL}?api_key={key}"
    
    headers = {"Content-Type": "application/json"}
    payload = {"query": query_or_mutation}
    if variables:
        payload["variables"] = variables
        
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        
        if "errors" in data and data["errors"]:
            error_msg = "; ".join([e.get("message", str(e)) for e in data["errors"]])
            raise RuntimeError(f"RunPod GraphQL Error: {error_msg}")
            
        return data.get("data", {})


async def start_pod(pod_id: str, api_key: Optional[str] = None) -> dict:
    """
    Start/Resume a stopped or paused RunPod instance.
    GraphQL mutation: podResume(input: {podId: "...", gpuCount: 1})
    """
    mutation = """
    mutation ResumePod($input: PodRentInterruptableInput!) {
        podResume(input: $input) {
            id
            desiredStatus
        }
    }
    """
    try:
        res = await execute_graphql(mutation, variables={"input": {"podId": pod_id, "gpuCount": 1}}, api_key=api_key)
        return res.get("podResume", {}) or {}
    except Exception:
        # Fallback if input structure differs
        query_simple = f'mutation {{ podResume(input: {{ podId: "{pod_id}", gpuCount: 1 }}) {{ id desiredStatus }} }}'
        res = await execute_graphql(query_simple, api_key=api_key)
        return res.get("podResume", {}) or {}


async def stop_pod(pod_id: str, api_key: Optional[str] = None) -> dict:
    """
    Stop/Pause a running RunPod instance to prevent idle GPU billing.
    Files in /workspace remain 100% preserved.
    GraphQL mutation: podStop(input: {podId: "..."})
    """
    mutation = """
    mutation StopPod($podId: String!) {
        podStop(input: {podId: $podId}) {
            id
            desiredStatus
        }
    }
    """
    res = await execute_graphql(mutation, variables={"podId": pod_id}, api_key=api_key)
    return res.get("podStop", {})


async def get_pod_status(pod_id: str, api_key: Optional[str] = None) -> dict:
    """
    Query current status, runtime info, and IP/ports of a specific pod.
    """
    query = """
    query PodInfo($podId: String!) {
        pod(input: {podId: $podId}) {
            id
            name
            desiredStatus
            lastStatusChange
            dockerArgs
            imageName
            gpuCount
            costPerHr
            runtime {
                uptimeInSeconds
                gpus {
                    id
                    gpuUtilPercentage
                    memoryUtilPercentage
                }
                ports {
                    ip
                    isIpPublic
                    privatePort
                    publicPort
                }
            }
        }
    }
    """
    res = await execute_graphql(query, variables={"podId": pod_id}, api_key=api_key)
    return res.get("pod", {})


async def list_user_pods(api_key: Optional[str] = None) -> List[dict]:
    """
    List all active and paused pods under the user's account.
    """
    query = """
    query MyPods {
        myself {
            pods {
                id
                name
                desiredStatus
                lastStatusChange
                gpuCount
                costPerHr
                imageName
                ports
            }
        }
    }
    """
    res = await execute_graphql(query, api_key=api_key)
    myself = res.get("myself", {})
    raw_pods = myself.get("pods", []) if myself else []

    formatted = []
    for pod in raw_pods:
        p_str = pod.get("ports", "") or ""
        # Determine best desktop/web port
        if "6901" in p_str:
            port = "6901"
        elif "6080" in p_str:
            port = "6080"
        elif "8888" in p_str:
            port = "8888"
        else:
            port = "6901"
        
        pod["httpPort"] = port
        formatted.append(pod)

    return formatted


async def create_pod(
    name: str,
    image_name: str,
    gpu_type_id: str = "NVIDIA RTX A6000",
    cloud_type: str = "SECURE",
    container_disk_in_gb: int = 60,
    volume_in_gb: int = 200,
    volume_mount_path: str = "/workspace",
    ports: str = "8444/http,22/tcp,8888/http",
    api_key: Optional[str] = None,
) -> dict:
    """
    Programmatically launch a new pod from a custom template or Docker image.
    """
    mutation = """
    mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
        podFindAndDeployOnDemand(input: $input) {
            id
            name
            desiredStatus
            imageName
            costPerHr
        }
    }
    """
    input_payload = {
        "name": name,
        "imageName": image_name,
        "gpuTypeId": gpu_type_id,
        "cloudType": cloud_type,
        "containerDiskInGb": container_disk_in_gb,
        "volumeInGb": volume_in_gb,
        "volumeMountPath": volume_mount_path,
        "ports": ports,
        "startJupyter": True,
        "startSsh": True,
    }
    res = await execute_graphql(mutation, variables={"input": input_payload}, api_key=api_key)
    return res.get("podFindAndDeployOnDemand", {})
