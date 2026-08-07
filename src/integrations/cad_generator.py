"""
cad_generator.py — Parametric Greenhouse CAD Floorplan Generator (.DXF)

Generates professional AutoCAD/FreeCAD compatible 2D & 3D .dxf floorplans
based on DSFC Excel demand calculations (crew size, crop area, aisle clearance).
"""

import os
import ezdxf
from ezdxf import units
from typing import Dict, Any

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "cad_exports")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_greenhouse_dxf(
    crew_size: int = 15,
    sol_duration: int = 14,
    crop_selection: str = "Spirulina, Dwarf Sunflower, Sugar Beet",
    aisle_width_m: float = 1.4,
    rack_width_m: float = 1.2,
    rack_length_m: float = 3.0,
    filename: str = "astrofood_greenhouse_floorplan.dxf"
) -> Dict[str, Any]:
    """
    Parametrically generates a DXF greenhouse floorplan.
    """
    doc = ezdxf.new(setup=True)
    doc.units = units.M
    msp = doc.modelspace()

    # Calculate parametric dimensions based on crew size
    racks_per_row = max(4, (crew_size // 3) + 2)
    num_rows = 4
    
    building_width = (num_rows * rack_width_m) + ((num_rows + 1) * aisle_width_m)
    building_length = (racks_per_row * rack_length_m) + 3.0 # plus end clearance

    # 1. Outer Perimeter Wall Layer (WALLS)
    doc.layers.add(name="WALLS", color=7) # White/Black
    msp.add_lwpolyline(
        [(0, 0), (building_width, 0), (building_width, building_length), (0, building_length), (0, 0)],
        dxfattribs={"layer": "WALLS", "lineweight": 50}
    )

    # 2. Vertical Hydroponic Racks (RACKS)
    doc.layers.add(name="RACKS", color=3) # Green
    rack_count = 0
    for r in range(num_rows):
        x_start = aisle_width_m + r * (rack_width_m + aisle_width_m)
        for c in range(racks_per_row):
            y_start = 1.5 + c * (rack_length_m + 0.5)
            # Add Rack polyline
            msp.add_lwpolyline(
                [
                    (x_start, y_start),
                    (x_start + rack_width_m, y_start),
                    (x_start + rack_width_m, y_start + rack_length_m),
                    (x_start, y_start + rack_length_m),
                    (x_start, y_start)
                ],
                dxfattribs={"layer": "RACKS"}
            )
            # Add rack label text
            msp.add_text(
                f"RACK-{rack_count+1}",
                dxfattribs={"layer": "RACKS", "height": 0.25}
            ).set_placement((x_start + 0.2, y_start + 1.2))
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
    msp.add_text(title_text, dxfattribs={"layer": "ANNOTATIONS", "height": 0.4}).set_placement((0.5, building_length + 2.2))
    msp.add_text(f"Overall Dimensions: {building_width:.1f}m x {building_length:.1f}m", dxfattribs={"layer": "ANNOTATIONS", "height": 0.3}).set_placement((0.5, building_length + 1.5))
    msp.add_text(f"Crop Targets: {crop_selection}", dxfattribs={"layer": "ANNOTATIONS", "height": 0.25}).set_placement((0.5, building_length + 0.9))

    # Save output DXF
    file_path = os.path.join(OUTPUT_DIR, filename)
    doc.saveas(file_path)

    return {
        "status": "success",
        "file_path": file_path,
        "filename": filename,
        "building_width_m": building_width,
        "building_length_m": building_length,
        "total_racks": rack_count,
        "crew_size": crew_size,
        "crop_selection": crop_selection
    }

if __name__ == "__main__":
    res = generate_greenhouse_dxf(crew_size=15)
    print("Generated DXF:", res)
