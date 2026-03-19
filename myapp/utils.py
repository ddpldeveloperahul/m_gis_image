import rasterio
import numpy as np
import os
import geopandas as gpd
import zipfile
from rasterio.warp import reproject, Resampling
from rasterio.features import shapes
from shapely.geometry import shape
from scipy.ndimage import binary_closing
from matplotlib.colors import ListedColormap
import matplotlib.pyplot as plt
import pandas as pd   # ✅ ADD THIS



def process_change(img2023_path, img2025_path, output_dir):

    os.makedirs(output_dir, exist_ok=True)

    # ---------------- READ 2023 ----------------
    with rasterio.open(img2023_path) as ref:
        img23 = ref.read(1).astype(np.float32)
        transform = ref.transform
        crs = ref.crs
        shape_img = img23.shape

    # ---------------- ALIGN 2025 ----------------
    with rasterio.open(img2025_path) as src:
        img25_raw = src.read(1).astype(np.float32)
        img25 = np.zeros(shape_img, dtype=np.float32)

        reproject(
            source=img25_raw,
            destination=img25,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=crs,
            resampling=Resampling.bilinear
        )

    # ---------------- NORMALIZATION ----------------
    def normalize(img):
        p2, p98 = np.percentile(img, (2, 98))
        return np.clip((img - p2) / (p98 - p2), 0, 1)

    img23_n = normalize(img23)
    img25_n = normalize(img25)

    # ---------------- DIFFERENCE ----------------
    diff = img25_n - img23_n

    # ---------------- THRESHOLD ----------------
    threshold = 0.6
    strong_change = np.abs(diff) > threshold

    # ---------------- CLEAN NOISE ----------------
    clean = binary_closing(strong_change, structure=np.ones((5, 5)))

    final_map = np.zeros(shape_img, dtype=np.uint8)
    final_map[clean] = 1

    # ====================================================
    # ---------------- SAVE TIFF ----------------
    # ====================================================

    tif_path = os.path.join(output_dir, "change.tif")

    new_profile = {
        'driver': 'GTiff',
        'height': final_map.shape[0],
        'width': final_map.shape[1],
        'count': 1,
        'dtype': rasterio.uint8,
        'crs': crs,
        'transform': transform,
        'nodata': 0
    }

    with rasterio.open(tif_path, 'w', **new_profile) as dst:
        dst.write(final_map.astype('uint8'), 1)

        # 🔥 Add threshold metadata
        dst.update_tags(
            THRESHOLD=str(threshold),
            DESCRIPTION="Change Detection Output",
            CREATOR="Django GIS System"
        )

    # ====================================================
    # ---------------- SAVE PNG ----------------
    # ====================================================

    png_path = os.path.join(output_dir, "change.png")

    plt.figure(figsize=(8, 8))
    plt.imshow(final_map, cmap=ListedColormap(["white", "blue"]))
    plt.title(f"Change Detection (Threshold = {threshold})")
    plt.axis("off")
    plt.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close()

    # ====================================================
    # ---------------- SAVE SHAPEFILE ----------------
    # ====================================================

    results = (
        {'properties': {'value': v}, 'geometry': s}
        for s, v in shapes(final_map, transform=transform)
        if v == 1
    )

    geoms = [shape(r['geometry']) for r in results]

    gdf = gpd.GeoDataFrame(geometry=geoms, crs=crs)

    shp_path = os.path.join(output_dir, "change.shp")
    gdf.to_file(shp_path)

    # ====================================================
    # ---------------- ZIP SHAPEFILE ----------------
    # ====================================================

    zip_path = os.path.join(output_dir, "change_shapefile.zip")

    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for ext in ['shp', 'shx', 'dbf', 'prj']:
            file_path = os.path.join(output_dir, f"change.{ext}")
            if os.path.exists(file_path):
                zipf.write(file_path, os.path.basename(file_path))

    # ====================================================
    # RETURN OUTPUT FILES
    # ====================================================

    return png_path, tif_path, zip_path

os.environ["SHAPE_RESTORE_SHX"] = "YES"
def process_spatial_join(main_path, change_path, output_dir):
    """
    Perform spatial join and return clean change detection result
    """
    os.makedirs(output_dir, exist_ok=True)
    shp_output = os.path.join(output_dir, "joined_output.shp")
    excel_output = os.path.join(output_dir, "joined_output.xlsx")

    # 🔹 Load files
    main = gpd.read_file(main_path)
    change = gpd.read_file(change_path)

    print("MAIN CRS:", main.crs)
    print("CHANGE CRS:", change.crs)

    # 🔹 CRS match
    if main.crs != change.crs:
        change = change.to_crs(main.crs)

    # 🔹 Detect ID column dynamically
    possible_cols = ['Id', 'id', 'ID', 'fid', 'FID', 'objectid']

    id_col = None
    for col in possible_cols:
        if col in change.columns:
            id_col = col
            break

    if id_col is None:
        raise Exception(f"No ID column found. Columns: {list(change.columns)}")

    print("Using ID column:", id_col)

    # 🔹 Spatial Join
    joined = gpd.sjoin(
        main,
        change[[id_col, 'geometry']],
        how='left',
        predicate='intersects'
    )

    # 🔹 Remove index column if exists
    if 'index_right' in joined.columns:
        joined = joined.drop(columns=['index_right'])

    # 🔥 IMPORTANT FIX (clean result)

    # Create change flag
    joined['changed'] = joined[id_col].notna()

    # Remove duplicates (one row per main feature)
    final = joined.groupby(joined.index).agg({
        'geometry': 'first',
        id_col: 'first',
        'changed': 'max'
    }).reset_index(drop=True)

    # 🔹 Save shapefile
    final.to_file(shp_output)

    # 🔹 Convert geometry to WKT for Excel
    excel_df = final.copy()
    excel_df['geometry'] = excel_df['geometry'].apply(
        lambda g: g.wkt if g else None
    )

    # 🔹 Save Excel
    with pd.ExcelWriter(excel_output) as writer:
        excel_df.to_excel(writer, sheet_name='All Data', index=False)
        excel_df[excel_df['changed'] == True].to_excel(writer, sheet_name='Changed', index=False)
        excel_df[excel_df['changed'] == False].to_excel(writer, sheet_name='Unchanged', index=False)

    # 🔹 Stats
    total = len(final)
    changed = int(final['changed'].sum())
    unchanged = total - changed

    print("Total:", total)
    print("Changed:", changed)
    print("Unchanged:", unchanged)

    return {
        "total": total,
        "changed": changed,
        "unchanged": unchanged,
        "shapefile": shp_output,
        "excel": excel_output
    }