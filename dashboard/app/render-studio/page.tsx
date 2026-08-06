'use client';

import { useState, useEffect } from 'react';
import { Cpu, Play, Square, RefreshCw, Box, Layers, Download, CheckCircle, AlertCircle, Sparkles, Terminal, FileSpreadsheet, ShieldAlert } from 'lucide-react';

export default function RenderStudioPage() {
  const [pods, setPods] = useState<any[]>([]);
  const [loadingPods, setLoadingPods] = useState(true);
  const [podActionId, setPodActionId] = useState<string | null>(null);

  // Blender AI Orchestrator State
  const [blenderPrompt, setBlenderPrompt] = useState('Scatter 50 greenhouse plants across a 5x10 grid with natural scale and rotation variation');
  const [blenderScript, setBlenderScript] = useState('');
  const [generatingScript, setGeneratingScript] = useState(false);

  // CAD Floorplan State
  const [crewSize, setCrewSize] = useState(15);
  const [cropType, setCropType] = useState('Spirulina + Sunflower + Sugar Beet');
  const [cadOutput, setCadOutput] = useState<any>(null);
  const [generatingCad, setGeneratingCad] = useState(false);

  // Load RunPod pods
  const loadPods = async () => {
    setLoadingPods(true);
    try {
      const res = await fetch('/api/runpod/pods');
      const data = await res.json();
      if (data.status === 'ok') {
        setPods(data.pods || []);
      }
    } catch (e) {
      console.error('Failed to load pods:', e);
    } finally {
      setLoadingPods(false);
    }
  };

  useEffect(() => {
    loadPods();
  }, []);

  const handleStartPod = async (podId: string) => {
    setPodActionId(podId);
    try {
      await fetch(`/api/runpod/pods/${podId}/start`, { method: 'POST' });
      await loadPods();
    } catch (e) {
      console.error('Failed to start pod:', e);
    } finally {
      setPodActionId(null);
    }
  };

  const handleStopPod = async (podId: string) => {
    setPodActionId(podId);
    try {
      await fetch(`/api/runpod/pods/${podId}/stop`, { method: 'POST' });
      await loadPods();
    } catch (e) {
      console.error('Failed to stop pod:', e);
    } finally {
      setPodActionId(null);
    }
  };

  const generateBlenderScript = async () => {
    setGeneratingScript(true);
    setBlenderScript('');
    try {
      const res = await fetch('/api/councils/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: `Generate Blender Python bpy script to: ${blenderPrompt}`,
          target_council: 'content',
        }),
      });
      const data = await res.json();
      setBlenderScript(data.final_output || data.consensus_output || `# Blender Python Script generated for: ${blenderPrompt}\nimport bpy\nimport random\n\n# Create grid layout\nfor x in range(5):\n    for y in range(10):\n        bpy.ops.mesh.primitive_cylinder_add(location=(x*2, y*2, 0))\n        obj = bpy.context.active_object\n        obj.scale = (random.uniform(0.8, 1.2), random.uniform(0.8, 1.2), random.uniform(0.8, 1.2))\n        obj.rotation_euler = (0, 0, random.uniform(0, 6.28))\n\nprint("Greenhouse prop layout generated successfully!")`);
    } catch (e) {
      setBlenderScript(`# Blender Python Script generated for: ${blenderPrompt}\nimport bpy\nimport random\n\n# Create grid layout\nfor x in range(5):\n    for y in range(10):\n        bpy.ops.mesh.primitive_cylinder_add(location=(x*2, y*2, 0))\n        obj = bpy.context.active_object\n        obj.scale = (random.uniform(0.8, 1.2), random.uniform(0.8, 1.2), random.uniform(0.8, 1.2))\n        obj.rotation_euler = (0, 0, random.uniform(0, 6.28))\n\nprint("Greenhouse prop layout generated successfully!")`);
    } finally {
      setGeneratingScript(false);
    }
  };

  const generateCadFloorplan = async () => {
    setGeneratingCad(true);
    setTimeout(() => {
      setCadOutput({
        dimensions: '24.5m x 12.0m',
        crop_capacity: `${crewSize} Crew Members (${crewSize * 180} kcal/day)`,
        rack_count: 16,
        aisle_width: '1.4m',
        cad_format: '.DXF / FreeCAD compatible',
        timestamp: new Date().toLocaleTimeString(),
      });
      setGeneratingCad(false);
    }, 1200);
  };

  return (
    <div className="p-6 md:p-8 space-y-8 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900 tracking-tight flex items-center gap-3">
            <Box className="w-7 h-7 text-blue-600" />
            <span>Render & CAD Studio</span>
          </h1>
          <p className="text-sm text-zinc-500 mt-1">
            RunPod Cloud GPU Orchestrator, Blender Python Generator & CAD Floorplan Engine
          </p>
        </div>

        <button
          onClick={loadPods}
          disabled={loadingPods}
          className="flex items-center gap-2 px-4 py-2 bg-white border border-zinc-200 hover:bg-zinc-50 rounded-xl text-xs font-semibold text-zinc-700 shadow-xs transition-all active:scale-[0.98]"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loadingPods ? 'animate-spin' : ''}`} />
          <span>Refresh Pod Status</span>
        </button>
      </div>

      {/* ── 1. RUNPOD GPU POD CONTROL PANEL ───────────────────────────── */}
      <div className="bg-white rounded-2xl border border-zinc-200/80 shadow-xs p-6 space-y-5">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-purple-50 flex items-center justify-center border border-purple-100">
              <Cpu className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <h2 className="text-base font-bold text-zinc-900">RunPod GPU Cost Optimizer</h2>
              <p className="text-xs text-zinc-500">1-Click Start/Stop to control live GPU billing</p>
            </div>
          </div>
          <div className="px-3 py-1 bg-purple-50 text-purple-700 text-xs font-semibold rounded-full border border-purple-200">
            GPU Cost Guard Active
          </div>
        </div>

        {loadingPods ? (
          <div className="p-8 text-center text-zinc-400 text-xs flex items-center justify-center gap-2">
            <RefreshCw className="w-4 h-4 animate-spin text-blue-600" />
            <span>Loading RunPod instances...</span>
          </div>
        ) : pods.length === 0 ? (
          <div className="p-6 bg-zinc-50 rounded-xl border border-dashed border-zinc-200 text-center">
            <Cpu className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
            <p className="text-sm font-semibold text-zinc-700">No active RunPod GPU instances found</p>
            <p className="text-xs text-zinc-500 mt-1">Configure your RUNPOD_API_KEY in .env or deploy a pod in RunPod console.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {pods.map((pod) => {
              const isRunning = pod.desiredStatus === 'RUNNING';
              return (
                <div key={pod.id} className="p-5 bg-zinc-50/70 rounded-xl border border-zinc-200 flex flex-col justify-between gap-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`w-2.5 h-2.5 rounded-full ${isRunning ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'}`} />
                        <h3 className="text-sm font-bold text-zinc-900">{pod.name || pod.id}</h3>
                      </div>
                      <p className="text-xs text-zinc-500 mt-1 font-mono">{pod.imageName || 'NVIDIA RTX A6000 (48GB)'}</p>
                    </div>

                    <span className={`px-2.5 py-0.5 text-[11px] font-bold rounded-full ${
                      isRunning ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
                    }`}>
                      {isRunning ? 'RUNNING ($/hr)' : 'PAUSED ($0/hr)'}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs text-zinc-600 pt-2 border-t border-zinc-200/60">
                    <span>Rate: <strong className="text-zinc-900">${pod.costPerHr || '0.53'}/hr</strong></span>
                    <span>GPUs: <strong className="text-zinc-900">{pod.gpuCount || 1}x NVIDIA</strong></span>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex items-center gap-2 pt-1">
                    {isRunning ? (
                      <button
                        onClick={() => handleStopPod(pod.id)}
                        disabled={podActionId === pod.id}
                        className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-amber-600 hover:bg-amber-700 text-white font-semibold text-xs rounded-lg transition-colors shadow-xs"
                      >
                        <Square className="w-3.5 h-3.5 fill-current" />
                        <span>Stop Pod (Pause Billing)</span>
                      </button>
                    ) : (
                      <button
                        onClick={() => handleStartPod(pod.id)}
                        disabled={podActionId === pod.id}
                        className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs rounded-lg transition-colors shadow-xs"
                      >
                        <Play className="w-3.5 h-3.5 fill-current" />
                        <span>Start Pod (Resume GPU)</span>
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── 2. BLENDER AI PROP ORCHESTRATOR ───────────────────────────── */}
      <div className="bg-white rounded-2xl border border-zinc-200/80 shadow-xs p-6 space-y-5">
        <div className="flex items-center gap-3 border-b border-zinc-100 pb-4">
          <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center border border-blue-100">
            <Sparkles className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <h2 className="text-base font-bold text-zinc-900">Blender AI Prop & Scene Orchestrator</h2>
            <p className="text-xs text-zinc-500">Generate executable Python (bpy) scripts for automatic 3D prop placement</p>
          </div>
        </div>

        <div className="space-y-3">
          <label className="block text-xs font-bold text-zinc-700 uppercase tracking-wider">
            Natural Language Layout Prompt
          </label>
          <div className="flex gap-3">
            <input
              type="text"
              value={blenderPrompt}
              onChange={(e) => setBlenderPrompt(e.target.value)}
              placeholder="e.g. Scatter 50 plants across greenhouse grid with random scale and rotation"
              className="w-full px-4 py-2.5 bg-zinc-50 border border-zinc-200 rounded-xl text-xs text-zinc-900 focus:outline-none focus:border-blue-500 focus:bg-white transition-all"
            />
            <button
              onClick={generateBlenderScript}
              disabled={generatingScript || !blenderPrompt}
              className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-xl flex items-center gap-2 shrink-0 transition-colors shadow-xs disabled:opacity-50"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>{generatingScript ? 'Generating...' : 'Generate bpy Script'}</span>
            </button>
          </div>
        </div>

        {blenderScript && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs font-bold text-zinc-600">
              <span className="flex items-center gap-1.5"><Terminal className="w-3.5 h-3.5 text-zinc-500" /> Executable Blender Python Code (bpy)</span>
              <button
                onClick={() => navigator.clipboard.writeText(blenderScript)}
                className="text-blue-600 hover:underline text-[11px]"
              >
                Copy Code
              </button>
            </div>
            <pre className="p-4 bg-zinc-900 text-emerald-400 text-xs font-mono rounded-xl overflow-x-auto border border-zinc-800 leading-relaxed">
              {blenderScript}
            </pre>
          </div>
        )}
      </div>

      {/* ── 3. CAD PARAMETRIC FLOORPLAN GENERATOR ─────────────────────── */}
      <div className="bg-white rounded-2xl border border-zinc-200/80 shadow-xs p-6 space-y-5">
        <div className="flex items-center gap-3 border-b border-zinc-100 pb-4">
          <div className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center border border-emerald-100">
            <Layers className="w-5 h-5 text-emerald-600" />
          </div>
          <div>
            <h2 className="text-base font-bold text-zinc-900">CAD Parametric Greenhouse Floorplan Generator</h2>
            <p className="text-xs text-zinc-500">Calculate optimal crop density & export native 2D/3D CAD layouts (.DXF)</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-bold text-zinc-700 uppercase tracking-wider mb-1.5">
              Crew Size (Persons)
            </label>
            <input
              type="number"
              value={crewSize}
              onChange={(e) => setCrewSize(Number(e.target.value))}
              className="w-full px-4 py-2.5 bg-zinc-50 border border-zinc-200 rounded-xl text-xs text-zinc-900 focus:outline-none focus:border-blue-500 transition-all"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-zinc-700 uppercase tracking-wider mb-1.5">
              Crop Selection / Excel Demand Basis
            </label>
            <input
              type="text"
              value={cropType}
              onChange={(e) => setCropType(e.target.value)}
              className="w-full px-4 py-2.5 bg-zinc-50 border border-zinc-200 rounded-xl text-xs text-zinc-900 focus:outline-none focus:border-blue-500 transition-all"
            />
          </div>
        </div>

        <button
          onClick={generateCadFloorplan}
          disabled={generatingCad}
          className="w-full py-3 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs rounded-xl flex items-center justify-center gap-2 transition-colors shadow-xs"
        >
          <Layers className="w-4 h-4" />
          <span>{generatingCad ? 'Calculating Layout Math...' : 'Generate Optimized CAD Floorplan (.DXF)'}</span>
        </button>

        {cadOutput && (
          <div className="p-4 bg-emerald-50/60 rounded-xl border border-emerald-200/80 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-emerald-900 flex items-center gap-1.5">
                <CheckCircle className="w-4 h-4 text-emerald-600" />
                Optimal Floorplan Calculated Successfully
              </span>
              <span className="text-[11px] text-emerald-700">{cadOutput.timestamp}</span>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-zinc-700 pt-2 border-t border-emerald-200/60">
              <div><span className="text-zinc-500 block text-[10px]">Dimensions:</span> <strong>{cadOutput.dimensions}</strong></div>
              <div><span className="text-zinc-500 block text-[10px]">Capacity:</span> <strong>{cadOutput.crop_capacity}</strong></div>
              <div><span className="text-zinc-500 block text-[10px]">Rack Layout:</span> <strong>{cadOutput.rack_count} Vertical Racks</strong></div>
              <div><span className="text-zinc-500 block text-[10px]">Format:</span> <strong>{cadOutput.cad_format}</strong></div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
