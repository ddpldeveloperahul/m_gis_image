from PIL import Image

from pytz import timezone
import rasterio
import numpy as np
import os
import cv2
import geopandas as gpd
import zipfile
from rasterio.warp import reproject, Resampling
from rasterio.features import shapes
from shapely.geometry import shape
from scipy.ndimage import binary_closing
from matplotlib.colors import ListedColormap
import matplotlib.pyplot as plt
import pandas as pd   # ✅ ADD THIS
from scipy.ndimage import binary_closing, binary_opening
import cv2
from skimage.morphology import remove_small_objects



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

        import matplotlib
        matplotlib.use('Agg')   # 🔥 MUST ADD THIS

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

    overlay = np.zeros((final_map.shape[0], final_map.shape[1], 4), dtype=np.uint8)
    overlay[final_map == 1] = [0, 0, 255, 210]
    Image.fromarray(overlay, mode='RGBA').save(png_path)

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


# def process_change(img2023_path, img2025_path, output_dir):

#     os.makedirs(output_dir, exist_ok=True)

#     # ==============================
#     # 🔹 READ 2023 (REFERENCE)
#     # ==============================
#     with rasterio.open(img2023_path) as ref:
#         img23 = ref.read(1).astype(np.float32)
#         transform = ref.transform
#         crs = ref.crs
#         shape_img = img23.shape

#     # ==============================
#     # 🔹 ALIGN 2025 → 2023 GRID
#     # ==============================
#     with rasterio.open(img2025_path) as src:
#         img25_raw = src.read(1).astype(np.float32)
#         img25 = np.zeros(shape_img, dtype=np.float32)

#         reproject(
#             source=img25_raw,
#             destination=img25,
#             src_transform=src.transform,
#             src_crs=src.crs,
#             dst_transform=transform,
#             dst_crs=crs,
#             resampling=Resampling.bilinear
#         )

#     # ==============================
#     # 🔹 NORMALIZATION (SAFE)
#     # ==============================
#     def normalize(img):
#         p2, p98 = np.percentile(img, (2, 98))

#         if p98 - p2 == 0:
#             return np.zeros_like(img)

#         return np.clip((img - p2) / (p98 - p2), 0, 1)

#     img23_n = normalize(img23)
#     img25_n = normalize(img25)

#     # ==============================
#     # 🔹 DIFFERENCE
#     # ==============================
#     diff = np.abs(img25_n - img23_n)

#     # ==============================
#     # 🔹 AUTO THRESHOLD
#     # ==============================
#     threshold = np.mean(diff) + 1.5 * np.std(diff)

#     strong_change = diff > threshold

#     # ==============================
#     # 🔹 NOISE REMOVAL
#     # ==============================
#     clean = binary_opening(strong_change, structure=np.ones((3, 3)))
#     clean = binary_closing(clean, structure=np.ones((5, 5)))

#     clean = remove_small_objects(clean.astype(bool), min_size=50)

#     # ==============================
#     # 🔹 FINAL MAP
#     # ==============================
#     final_map = np.zeros(shape_img, dtype=np.uint8)
#     final_map[clean] = 1

#     # ==============================
#     # 🔹 SAVE TIFF
#     # ==============================
#     tif_path = os.path.join(output_dir, "change.tif")

#     profile = {
#         'driver': 'GTiff',
#         'height': final_map.shape[0],
#         'width': final_map.shape[1],
#         'count': 1,
#         'dtype': rasterio.uint8,
#         'crs': crs,
#         'transform': transform,
#         'nodata': 0
#     }

#     with rasterio.open(tif_path, 'w', **profile) as dst:
#         dst.write(final_map.astype('uint8'), 1)
#         dst.update_tags(
#             THRESHOLD=str(threshold),
#             DESCRIPTION="Change Detection Output",
#             CREATOR="GIS Django System"
#         )

#     # ==============================
#     # 🔹 SAVE PNG (OVERLAY)
#     # ==============================
#     png_path = os.path.join(output_dir, "change.png")

#     overlay = np.zeros((final_map.shape[0], final_map.shape[1], 4), dtype=np.uint8)
#     overlay[final_map == 1] = [0, 0, 255, 210]  # Blue overlay

#     Image.fromarray(overlay, mode='RGBA').save(png_path)

#     # ==============================
#     # 🔹 SAVE SHAPEFILE
#     # ==============================
#     results = (
#         {'properties': {'value': v}, 'geometry': s}
#         for s, v in shapes(final_map, transform=transform)
#         if v == 1
#     )

#     geoms = [shape(r['geometry']) for r in results]

#     if len(geoms) == 0:
#         gdf = gpd.GeoDataFrame(geometry=[], crs=crs)
#     else:
#         gdf = gpd.GeoDataFrame(geometry=geoms, crs=crs)

#     shp_path = os.path.join(output_dir, "change.shp")
#     gdf.to_file(shp_path)

#     # ==============================
#     # 🔹 ZIP SHAPEFILE
#     # ==============================
#     zip_path = os.path.join(output_dir, "change_shapefile.zip")

#     with zipfile.ZipFile(zip_path, 'w') as zipf:
#         for ext in ['shp', 'shx', 'dbf', 'prj', 'cpg']:
#             file_path = os.path.join(output_dir, f"change.{ext}")
#             if os.path.exists(file_path):
#                 zipf.write(file_path, os.path.basename(file_path))

#     # ==============================
#     # 🔹 RETURN
#     # ==============================
#     return png_path, tif_path, zip_path


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
    
    # Convert TRUE/FALSE to YES/NO
    excel_df['changed'] = excel_df['changed'].map({True: 'YES', False: 'NO'})

    # 🔹 Save Excel
    with pd.ExcelWriter(excel_output) as writer:
        excel_df.to_excel(writer, sheet_name='All Data', index=False)
        excel_df[excel_df['changed'] == 'YES'].to_excel(writer, sheet_name='Changed', index=False)
        excel_df[excel_df['changed'] == 'NO'].to_excel(writer, sheet_name='Unchanged', index=False)

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


import cv2
import numpy as np

def align_images(img1, img2):
    img1_gray = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    img2_gray = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(5000)
    kp1, des1 = orb.detectAndCompute(img1_gray, None)
    kp2, des2 = orb.detectAndCompute(img2_gray, None)

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = matcher.match(des1, des2)
    matches = sorted(matches, key=lambda x: x.distance)

    pts1 = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1,1,2)
    pts2 = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1,1,2)

    matrix, _ = cv2.findHomography(pts2, pts1, cv2.RANSAC, 5.0)

    aligned = cv2.warpPerspective(img2, matrix, (img1.shape[1], img1.shape[0]))

    return aligned

