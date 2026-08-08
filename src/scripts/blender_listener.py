import os
import tempfile
import subprocess
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="RunPod Blender AI Socket Bridge")

class BpyScriptRequest(BaseModel):
    script: str
    render: bool = True

@app.post("/api/blender/execute")
async def execute_blender_script(req: BpyScriptRequest):
    """
    Executes a provided Python (bpy) script in Blender in the background.
    If render=True, it expects the script to trigger a render, and we return the PNG.
    """
    if not req.script.strip():
        raise HTTPException(status_code=400, detail="Empty script provided")

    # 1. Write the script to a temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        script_path = f.name
        f.write(req.script)
        
        # If rendering, append code to save the render explicitly just in case
        if req.render:
            f.write(f"\nimport bpy\n")
            f.write(f"bpy.context.scene.render.filepath = '{script_path}_render.png'\n")
            f.write(f"bpy.ops.render.render(write_still=True)\n")

    # 2. Execute via Blender background mode
    # Assuming standard linux path for KasmVNC blender install
    blender_bin = "/usr/bin/blender"
    if not os.path.exists(blender_bin):
        blender_bin = "blender" # fallback to PATH

    cmd = [
        blender_bin,
        "-b", # background mode
        "-P", script_path # run python script
    ]

    print(f"Executing: {' '.join(cmd)}")
    
    try:
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if process.returncode != 0:
            print("Blender Error Log:", process.stderr)
            raise HTTPException(status_code=500, detail=f"Blender Execution Failed:\n{process.stderr}")

        if req.render:
            render_path = f"{script_path}_render.png"
            if os.path.exists(render_path):
                return FileResponse(render_path, media_type="image/png")
            else:
                return {"status": "success", "message": "Script executed, but no render output was generated.", "log": process.stdout}

        return {"status": "success", "message": "Script executed successfully.", "log": process.stdout}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Blender execution timed out (limit: 120s)")
    finally:
        # Cleanup
        if os.path.exists(script_path):
            os.remove(script_path)

if __name__ == "__main__":
    import uvicorn
    # Run on port 8001 so it doesn't conflict with KasmVNC on 6901
    uvicorn.run(app, host="0.0.0.0", port=8001)
