"""
Generate high-resolution visualization figures for the technical report.
"""

import os

os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource
import numpy as np

from app.kml_parser import KMLParser
from app.dem_generator import DEMGenerator
from app.hydrology import HydrologyEngine
from app.pond_siting import PondSitingEngine


def generate_report_figures():
    output_dir = os.path.join(os.path.dirname(__file__), "assets")
    os.makedirs(output_dir, exist_ok=True)

    kml_path = os.path.join(os.path.dirname(__file__), "contours_1m.kml")
    parser = KMLParser()
    data = parser.parse(kml_path)

    dem_gen = DEMGenerator(default_resolution_m=10.0)
    dem = dem_gen.generate_dem(data)

    hydro = HydrologyEngine()
    results = hydro.analyze(dem)

    pond_engine = PondSitingEngine()
    candidate_sites = pond_engine.find_optimal_sites(dem, results, num_candidates=5)
    top_site = candidate_sites[0]

    top_grid = (top_site["grid_index"]["row"], top_site["grid_index"]["col"])
    catchment = hydro.delineate_catchment(top_grid, results["flow_direction"], dem)

    # 1. 2D & 3D Hillshade DEM Map with Catchment and Pond Sites
    fig, ax = plt.subplots(figsize=(10, 8), dpi=200)
    ls = LightSource(azdeg=315, altdeg=45)
    rgb = ls.shade(
        dem.elevation, cmap=plt.cm.terrain, blend_mode="overlay", vert_exag=3
    )

    extent = [
        dem.x_coords[0] / 1000,
        dem.x_coords[-1] / 1000,
        dem.y_coords[0] / 1000,
        dem.y_coords[-1] / 1000,
    ]
    im = ax.imshow(rgb, extent=extent, origin="lower")

    # Overlay Catchment Mask Contour
    mask = catchment["catchment_mask"].astype(float)
    cs = ax.contour(
        mask,
        levels=[0.5],
        extent=extent,
        origin="lower",
        colors=["#00E5FF"],
        linewidths=2.5,
    )

    # Overlay Stream Network
    stream_mask = results["flow_accumulation"] >= np.percentile(
        results["flow_accumulation"], 98.0
    )
    # Scatter stream cells
    sy, sx = np.where(stream_mask)
    ax.scatter(
        dem.x_coords[sx] / 1000,
        dem.y_coords[sy] / 1000,
        s=1,
        c="#0288D1",
        alpha=0.6,
        label="Drainage Network",
    )

    # Plot Recommended Pond Location
    top_e = top_site["utm_coordinates"]["easting"] / 1000
    top_n = top_site["utm_coordinates"]["northing"] / 1000
    ax.scatter(
        top_e,
        top_n,
        s=160,
        c="#00E676",
        edgecolors="#000000",
        linewidth=2,
        zorder=10,
        label=f"Recommended Pond Site (Score: {top_site['suitability_score']})",
    )

    # Plot Alternative Candidates
    for site in candidate_sites[1:]:
        se = site["utm_coordinates"]["easting"] / 1000
        sn = site["utm_coordinates"]["northing"] / 1000
        ax.scatter(
            se, sn, s=90, c="#FF9100", edgecolors="#000000", linewidth=1.5, zorder=9
        )

    ax.set_title(
        "Terrain Elevation, Drainage Streams & Delineated Watershed Catchment",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax.set_xlabel("UTM Easting (km)", fontsize=10)
    ax.set_ylabel("UTM Northing (km)", fontsize=10)
    ax.legend(loc="upper right", framealpha=0.9)
    plt.tight_layout()

    map_path = os.path.join(output_dir, "catchment_terrain_map.png")
    fig.savefig(map_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"✓ Saved {map_path}")

    # 2. Multi-Panel Hydrological Analysis (DEM, Flow Accumulation, Slope, Depression Depth)
    fig, axs = plt.subplots(2, 2, figsize=(14, 11), dpi=200)

    # Panel A: DEM Elevation
    im0 = axs[0, 0].imshow(dem.elevation, cmap="terrain", origin="lower")
    axs[0, 0].set_title("A. Digital Elevation Model (DEM, m MSL)", fontweight="bold")
    plt.colorbar(im0, ax=axs[0, 0], fraction=0.046, pad=0.04)

    # Panel B: Log Flow Accumulation
    im1 = axs[0, 1].imshow(
        np.log1p(results["flow_accumulation"]), cmap="Blues", origin="lower"
    )
    axs[0, 1].set_title(
        "B. Log-Scaled Flow Accumulation (Drainage Network)", fontweight="bold"
    )
    plt.colorbar(im1, ax=axs[0, 1], fraction=0.046, pad=0.04)

    # Panel C: Terrain Slope (%)
    im2 = axs[1, 0].imshow(dem.slope_percent, cmap="YlOrRd", origin="lower", vmax=20)
    axs[1, 0].set_title("C. Terrain Slope (%) & Basin Stability", fontweight="bold")
    plt.colorbar(im2, ax=axs[1, 0], fraction=0.046, pad=0.04)

    # Panel D: Topographic Depressions / Sinks (m)
    im3 = axs[1, 1].imshow(
        results["depression_depth"], cmap="PuBuGn", origin="lower", vmax=6
    )
    axs[1, 1].set_title(
        "D. Topographic Depressions / Natural Storage Bowls (m)", fontweight="bold"
    )
    plt.colorbar(im3, ax=axs[1, 1], fraction=0.046, pad=0.04)

    for ax in axs.flat:
        ax.set_xlabel("Grid X (cells)")
        ax.set_ylabel("Grid Y (cells)")

    plt.tight_layout()
    hydrology_path = os.path.join(output_dir, "hydrology_panels.png")
    fig.savefig(hydrology_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"✓ Saved {hydrology_path}")


if __name__ == "__main__":
    generate_report_figures()
