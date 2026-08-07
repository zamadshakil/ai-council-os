import os

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")
POD_ID = os.getenv("DEFAULT_RUNPOD_POD_ID", "b1thgw95x1n3d4")  # superb_pink_ptarmigan
URL = f"https://api.runpod.io/graphql?api_key={RUNPOD_API_KEY}"

async def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if action == "start":
        print("🚀 Requesting RunPod to START superb_pink_ptarmigan...")
        q = f'mutation {{ podResume(input: {{ podId: "{POD_ID}", gpuCount: 1 }}) {{ id desiredStatus }} }}'
        async with httpx.AsyncClient() as client:
            res = await client.post(URL, json={"query": q})
            print("RunPod Response:", res.json())
            
    elif action == "stop":
        print("🛑 Requesting RunPod to STOP superb_pink_ptarmigan (Pause Billing)...")
        q = f'mutation {{ podStop(input: {{ podId: "{POD_ID}" }}) {{ id desiredStatus }} }}'
        async with httpx.AsyncClient() as client:
            res = await client.post(URL, json={"query": q})
            print("RunPod Response:", res.json())

if __name__ == "__main__":
    asyncio.run(main())
