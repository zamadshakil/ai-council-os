"""
cad_generator.py — Parametric Greenhouse CAD Floorplan Generator (.DXF)

Generates professional AutoCAD/FreeCAD compatible 2D/3D .dxf floorplans
dynamically calculated from DSFC Excel demand parameters (crew size, crop yield,
specific crop varieties, rack spacing, and aisle clearances).
"""

import os
import ezdxf
from ezdxf import units
from typing import Dict, Any, List, Optional

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "cad_exports")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Color mapping for different crop types in CAD
CROP_COLORS = {
    "tomato": 1,        # Red
    "strawberry": 210,  # Pink
    "spinach": 3,       # Green
    "lettuce": 4,       # Cyan
    "wheat": 2,         # Yellow
    "soybean": 5,       # Blue
    "carrot": 30,       # Orange
    "pea": 80,          # Light Green
    "default": 3        # Green
}

def generate_greenhouse_dxf(
    crew_size: int = 15,
    sol_duration: int = 14,
    crop_selection: str = "Spirulina, Dwarf Sunflower, Sugar Beet",
    crop_details: Optional[List[Dict[str, Any]]] = None,
    aisle_width_m: float = 1.4,
    rack_width_m: float = 1.2,
    rack_length_m: float = 3.0,
    filename: str = "astrofood_greenhouse_floorplan.dxf"
) -> Dict[str, Any]:
    """
    Parametrically generates a 2D/3D DXF greenhouse floorplan.
    Dynamically adjusts grid size, rack count, and crop layer colors based on Excel data.
    """
    doc = ezdxf.new(setup=True)
    doc.units = units.M
    msp = doc.modelspace()

    # Calculate total racks based on crew size & crop yield details
    if crop_details and len(crop_details) > 0:
        total_crops = len(crop_details)
        racks_per_row = max(4, (total_crops // 2) + 2)
        num_rows = max(3, (total_crops // racks_per_row) + 2)
    else:
        racks_per_row = max(4, (crew_size // 3) + 2)
        num_rows = 4

    building_width = (num_rows * rack_width_m) + ((num_rows + 1) * aisle_width_m)
    building_length = (racks_per_row * rack_length_m) + 3.5 # plus end clearance

    # 1. Outer Perimeter Wall Layer (WALLS)
    doc.layers.add(name="WALLS", color=7) # White/Black
    msp.add_lwpolyline(
        [(0, 0), (building_width, 0), (building_width, building_length), (0, building_length), (0, 0)],
        dxfattribs={"layer": "WALLS", "lineweight": 50}
    )

    # 2. Vertical Hydroponic Racks (RACKS & CROP ZONES)
    rack_count = 0
    crop_list = crop_details if crop_details else []
    
    for r in range(num_rows):
        x_start = aisle_width_m + r * (rack_width_m + aisle_width_m)
        for c in range(racks_per_row):
            y_start = 1.5 + c * (rack_length_m + 0.5)
            
            # Determine crop name and layer for this rack
            if rack_count < len(crop_list):
                crop_info = crop_list[rack_count]
                c_name = crop_info.get("name", f"Crop-{rack_count+1}")
                c_mass = crop_info.get("mass_g", 0)
                label_str = f"{c_name} ({c_mass}g)" if c_mass > 0 else c_name
            else:
                c_name = f"RACK-{rack_count+1}"
                label_str = c_name

            layer_name = f"CROP_{c_name.split()[0].upper()}"[:15]
            
            # Pick CAD color based on crop category
            c_key = c_name.lower()
            color_code = 3 # default green
            for key, col in CROP_COLORS.items():
                if key in c_key:
                    color_code = col
                    break
            
            if layer_name not in doc.layers:
                doc.layers.add(name=layer_name, color=color_code)

            # Add Rack polyline
            msp.add_lwpolyline(
                [
                    (x_start, y_start),
                    (x_start + rack_width_m, y_start),
                    (x_start + rack_width_m, y_start + rack_length_m),
                    (x_start, y_start + rack_length_m),
                    (x_start, y_start)
                ],
                dxfattribs={"layer": layer_name}
            )
            
            # Add rack label text
            msp.add_text(
                label_str[:18],
                dxfattribs={"layer": layer_name, "height": 0.22}
            ).set_placement((x_start + 0.1, y_start + 1.2))
            
            rack_count += 1

    # 3. Aisles & Service Corridor (AISLES)
    doc.layers.add(name="AISLES", color=1) # Red dashed
    if "DASHED" not in doc.linetypes:
        doc.linetypes.add("DASHED", pattern="A,.5,-.25", description="Dashed line")
    for r in range(num_rows + 1):
        x_aisle = r * (rack_width_m + aisle_width_m) + (aisle_width_m / 2)
        msp.add_line(
            (x_aisle, 0.5),
            (x_aisle, building_length - 0.5),
            dxfattribs={"layer": "AISLES", "linetype": "DASHED"}
        )

    # 4. Annotation Titleblock (TEXT)
    doc.layers.add(name="ANNOTATIONS", color=2) # Yellow
    title_text = f"ASTROFOOD MARS GREENHOUSE FLOORPLAN ({crew_size} CREW, {sol_duration} SOLS)"
    msp.add_text(title_text, dxfattribs={"layer": "ANNOTATIONS", "height": 0.4}).set_placement((0.5, building_length + 2.4))
    msp.add_text(f"Overall Dimensions: {building_width:.1f}m x {building_length:.1f}m | Total Racks: {rack_count}", dxfattribs={"layer": "ANNOTATIONS", "height": 0.3}).set_placement((0.5, building_length + 1.7))
    msp.add_text(f"Crop Basis: {crop_selection[:60]}", dxfattribs={"layer": "ANNOTATIONS", "height": 0.25}).set_placement((0.5, building_length + 1.1))

    # Save output DXF
    file_path = os.path.join(OUTPUT_DIR, filename)
    doc.saveas(file_path)

    return {
        "status": "success",
        "file_path": file_path,
        "filename": filename,
        "building_width_m": round(building_width, 1),
        "building_length_m": round(building_length, 1),
        "total_racks": rack_count,
        "crew_size": crew_size,
        "crop_selection": crop_selection,
        "crops_parsed_count": len(crop_list)
    }

if __name__ == "__main__":
    res = generate_greenhouse_dxf(crew_size=15)
    print("Generated DXF:", res)
