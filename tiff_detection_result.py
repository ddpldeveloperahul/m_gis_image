import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk
import rasterio
import numpy as np
from scipy.ndimage import binary_closing
from rasterio.warp import reproject, Resampling
from rasterio.features import shapes
from shapely.geometry import shape
import geopandas as gpd
import pandas as pd
import os, zipfile, shutil
from matplotlib.colors import ListedColormap
import matplotlib.pyplot as plt

# ================= GLOBAL =================
old_img = None
new_img = None
old_path = None
new_path = None
result_img = None
scale = 1

old_shapefile_path = None
spatial_zip_path = None
spatial_result_gdf = None

# ================= AUTO ZIP =================
def get_latest_zip():
    folder = "output"
    if not os.path.exists(folder):
        return None
    zip_files = [f for f in os.listdir(folder) if f.endswith(".zip")]
    if not zip_files:
        return None
    zip_files.sort(key=lambda x: os.path.getmtime(os.path.join(folder, x)), reverse=True)
    return os.path.join(folder, zip_files[0])

# ================= READ =================
def read_tif(path):
    with rasterio.open(path) as src:
        img = src.read()
        if img.shape[0] >= 3:
            img = np.transpose(img[:3], (1, 2, 0))
        else:
            img = img[0]
        img = (img - img.min()) / (img.max() - img.min()) * 255
        return img.astype(np.uint8)

# ================= LOAD =================
def load_old():
    global old_img, old_path
    path = filedialog.askopenfilename(filetypes=[("TIF", "*.tif *.tiff")])
    if path:
        old_path = path
        old_img = read_tif(path)
        show_fixed(old_img, old_label)

def load_new():
    global new_img, new_path
    path = filedialog.askopenfilename(filetypes=[("TIF", "*.tif *.tiff")])
    if path:
        new_path = path
        new_img = read_tif(path)
        show_fixed(new_img, new_label)

# ================= SHOW =================
def show_fixed(img, label):
    img = Image.fromarray(img)
    img = img.resize((300, 300))
    imgtk = ImageTk.PhotoImage(img)
    label.config(image=imgtk)
    label.image = imgtk

# ================= DETECTION =================
def run_detection():
    global result_img

    with rasterio.open(old_path) as ref:
        img23 = ref.read(1).astype(float)
        transform = ref.transform
        crs = ref.crs
        shape_img = img23.shape

    with rasterio.open(new_path) as src:
        img25_raw = src.read(1).astype(float)
        img25 = np.zeros(shape_img)

        reproject(
            source=img25_raw,
            destination=img25,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=crs,
            resampling=Resampling.bilinear
        )

    diff = (img25 - img23)
    diff = (diff - diff.min()) / (diff.max() - diff.min())

    mask = np.abs(diff) > 0.5
    clean = binary_closing(mask, structure=np.ones((5,1)))

    result = np.zeros_like(img23, dtype=np.uint8)
    result[clean] = 1

    os.makedirs("output", exist_ok=True)

    plt.imshow(result, cmap=ListedColormap(["white", "#0047FF"]))
    plt.axis("off")
    plt.savefig("output/change_blue.png", bbox_inches="tight", pad_inches=0)
    plt.close()

    result_img = np.array(Image.open("output/change_blue.png"))

    save_outputs(result, transform, crs)

# ================= SAVE =================
def save_outputs(result, transform, crs):
    with rasterio.open(
        "output/change.tif", 'w',
        driver='GTiff',
        height=result.shape[0],
        width=result.shape[1],
        count=1,
        dtype=rasterio.uint8,
        crs=crs,
        transform=transform
    ) as dst:
        dst.write(result, 1)

    geoms = [shape(g) for g, v in shapes(result, transform=transform) if v == 1]

    if geoms:
        gpd.GeoDataFrame(geometry=geoms, crs=crs).to_file("output/change.shp")

        with zipfile.ZipFile("output/change.zip", 'w') as z:
            for ext in ['shp','shx','dbf','prj']:
                f = f"output/change.{ext}"
                if os.path.exists(f):
                    z.write(f, os.path.basename(f))

# ================= DOWNLOAD =================
def download_tif():
    path = filedialog.asksaveasfilename(defaultextension=".tif", initialfile="change.tif")
    if path:
        shutil.copy("output/change.tif", path)

def download_shp():
    path = filedialog.asksaveasfilename(defaultextension=".zip", initialfile="change_shapefile.zip")
    if path:
        shutil.copy("output/change.zip", path)

# ================= ZOOM =================
def update_zoom():
    if result_img is None:
        return
    img = Image.fromarray(result_img)
    size = int(400 * scale)
    img = img.resize((size, size))
    imgtk = ImageTk.PhotoImage(img)
    result_label.config(image=imgtk)
    result_label.image = imgtk

def zoom_in():
    global scale
    scale += 0.2
    update_zoom()

def zoom_out():
    global scale
    if scale > 0.4:
        scale -= 0.2
        update_zoom()

def reset_zoom():
    global scale
    scale = 1
    update_zoom()

def show_old():
    show_fixed(old_img, result_label)

def show_new():
    show_fixed(new_img, result_label)

# ================= PAGE =================
def show_result_page():
    run_detection()
    upload_frame.pack_forget()
    result_frame.pack(fill="both", expand=True)
    update_zoom()
    result_status.config(text="✅ Change Detection Done")

def go_back():
    result_frame.pack_forget()
    upload_frame.pack(fill="both", expand=True)

# ================= SPATIAL =================
def go_to_spatial():
    global spatial_zip_path
    spatial_zip_path = get_latest_zip()

    if spatial_zip_path:
        auto_label.config(text=f"✅ Auto Loaded: {os.path.basename(spatial_zip_path)}", fg="green")
    else:
        auto_label.config(text="❌ No shapefile found", fg="red")

    result_frame.pack_forget()
    spatial_frame.pack(fill="both", expand=True)

def load_old_shapefile():
    global old_shapefile_path

    path = filedialog.askopenfilename(
        filetypes=[
            ("Shapefile & ZIP", "*.shp *.zip"),
            ("Shapefile", "*.shp"),
            ("ZIP files", "*.zip"),
            ("All Files", "*.*")
        ]
    )

    if not path:
        return

    if path.lower().endswith(".zip"):
        extract_path = "output/old_extract"

        if os.path.exists(extract_path):
            shutil.rmtree(extract_path)

        os.makedirs(extract_path)

        try:
            with zipfile.ZipFile(path, 'r') as z:
                z.extractall(extract_path)
        except:
            spatial_status.config(text="❌ Invalid ZIP", fg="red")
            return

        shp_files = [f for f in os.listdir(extract_path) if f.endswith(".shp")]

        if not shp_files:
            spatial_status.config(text="❌ No SHP in ZIP", fg="red")
            return

        old_shapefile_path = os.path.join(extract_path, shp_files[0])
        spatial_status.config(text="✅ ZIP loaded", fg="green")

    else:
        old_shapefile_path = path
        spatial_status.config(text="✅ SHP loaded", fg="green")

    old_shp_label.config(text=os.path.basename(path))



def extract_and_find_shp(zip_path, extract_to):
    if os.path.exists(extract_to):
        shutil.rmtree(extract_to)

    os.makedirs(extract_to)

    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(extract_to)
    except Exception as e:
        print("ZIP ERROR:", e)
        return None

    # 🔥 SAME AS DJANGO
    for root, dirs, files in os.walk(extract_to):
        for file in files:
            if file.lower().endswith('.shp'):
                return os.path.join(root, file)

    return None



def process_spatial_join(main_shp, change_shp, output_folder):
    os.makedirs(output_folder, exist_ok=True)

    # read files
    gdf1 = gpd.read_file(main_shp)
    gdf2 = gpd.read_file(change_shp)

    # CRS match
    if gdf1.crs != gdf2.crs:
        gdf2 = gdf2.to_crs(gdf1.crs)

    # spatial join
    joined = gpd.sjoin(gdf1, gdf2, how="left", predicate="intersects")

    # changed / unchanged logic
    joined["changed"] = joined.index_right.notnull()

    total = len(joined)
    changed = joined["changed"].sum()
    unchanged = total - changed

    # save excel
    excel_path = os.path.join(output_folder, "spatial_result.xlsx")
    joined.to_excel(excel_path, index=False)

    # save shapefile
    shp_path = os.path.join(output_folder, "spatial_result.shp")
    joined.to_file(shp_path)

    # zip shapefile
    zip_path = os.path.join(output_folder, "spatial_result.zip")
    with zipfile.ZipFile(zip_path, 'w') as z:
        for ext in ['shp','shx','dbf','prj','cpg']:
            f = shp_path.replace(".shp", f".{ext}")
            if os.path.exists(f):
                z.write(f, os.path.basename(f))

    return {
        "total": int(total),
        "changed": int(changed),
        "unchanged": int(unchanged)
    }

def run_spatial_join():
    global spatial_result_gdf

    if old_shapefile_path is None:
        spatial_status.config(text="❌ Select old shapefile", fg="red")
        return

    if spatial_zip_path is None:
        spatial_status.config(text="❌ No change shapefile ZIP", fg="red")
        return

    main_shp = None
    change_shp = None

    # ✅ OLD FILE HANDLE
    if old_shapefile_path.endswith(".zip"):
        main_shp = extract_and_find_shp(old_shapefile_path, "output/main")
    else:
        main_shp = old_shapefile_path

    # ✅ CHANGE FILE HANDLE (AUTO ZIP)
    change_shp = extract_and_find_shp(spatial_zip_path, "output/change")

    print("MAIN SHP:", main_shp)
    print("CHANGE SHP:", change_shp)

    if not main_shp:
        spatial_status.config(text="❌ OLD SHP not found", fg="red")
        return

    if not change_shp:
        spatial_status.config(text="❌ CHANGE SHP not found in ZIP", fg="red")
        return

    try:
        # 🔥 SAME LOGIC AS UTILS
        result = process_spatial_join(main_shp, change_shp, "output")

    except Exception as e:
        spatial_status.config(text=f"❌ Error: {str(e)}", fg="red")
        print(e)
        return

    # ✅ RESULT SHOW
    show_spatial_result(
        result["total"],
        result["changed"],
        result["unchanged"]
    )

# ================= RESULT PAGE =================
def show_spatial_result(t, c, u):
    spatial_frame.pack_forget()
    spatial_result_frame.pack(fill="both", expand=True)

    total_label.config(text=str(t))
    changed_label.config(text=str(c))
    unchanged_label.config(text=str(u))

def download_excel():
    path = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile="result.xlsx")
    if path:
        shutil.copy("output/spatial_result.xlsx", path)

def download_spatial_zip():
    path = filedialog.asksaveasfilename(defaultextension=".zip", initialfile="spatial_result.zip")
    if path:
        shutil.copy("output/spatial_result.zip", path)

# ================= UI =================

root = tk.Tk()
root.title("GIS Tool")
root.geometry("800x700")
root.configure(bg="#0f172a")  # dark background

# ===== MODERN MAIN PAGE =====
upload_frame = tk.Frame(root, bg="#f5f6fa")
upload_frame.pack(fill="both", expand=True)

# ===== TITLE =====
tk.Label(upload_frame,
         text="🛰 Change Detection Tool",
         font=("Arial", 20, "bold"),
         bg="#f5f6fa").pack(pady=20)

# ===== BUTTON STYLE =====
def modern_btn(parent, text, color, command):
    return tk.Button(parent,
                     text=text,
                     bg=color,
                     fg="white",
                     font=("Arial", 12, "bold"),
                     relief="flat",
                     width=20,
                     height=2,
                     command=command)

btn_frame = tk.Frame(upload_frame, bg="#f5f6fa")
btn_frame.pack(pady=10)

modern_btn(btn_frame, "Load OLD TIF", "#6c757d", load_old).pack(pady=5)
modern_btn(btn_frame, "Load NEW TIF", "#6c757d", load_new).pack(pady=5)

modern_btn(btn_frame, "🚀 Run Change Detection", "#1e66d0",
           show_result_page).pack(pady=10)

# ===== IMAGE CARDS =====
img_frame = tk.Frame(upload_frame, bg="#f5f6fa")
img_frame.pack(pady=20)

def image_card(parent):
    frame = tk.Frame(parent, bg="white", width=320, height=320)
    frame.pack(side="left", padx=20)
    frame.pack_propagate(False)

    lbl = tk.Label(frame, bg="white")
    lbl.pack(expand=True)

    return lbl

old_label = image_card(img_frame)
new_label = image_card(img_frame)

# -------- RESULT --------
# -------- RESULT (MODERN) --------
result_frame = tk.Frame(root, bg="#f5f6fa")

tk.Label(result_frame,
         text="🧠 Change Detection Result",
         font=("Segoe UI", 20, "bold"),
         bg="#f5f6fa").pack(pady=20)

# IMAGE CARD
img_card = tk.Frame(result_frame, bg="white", width=420, height=420)
img_card.pack(pady=10)
img_card.pack_propagate(False)

result_label = tk.Label(img_card, bg="white")
result_label.pack(expand=True)

# CONTROLS
control = tk.Frame(result_frame, bg="#f5f6fa")
control.pack(pady=10)

def ctrl_btn(text, cmd):
    return tk.Button(control,
                     text=text,
                     command=cmd,
                     bg="#e9ecef",
                     relief="flat",
                     font=("Segoe UI", 9),
                     padx=10)

ctrl_btn("Zoom In", zoom_in).grid(row=0, column=0, padx=4)
ctrl_btn("Zoom Out", zoom_out).grid(row=0, column=1, padx=4)
ctrl_btn("Reset", reset_zoom).grid(row=0, column=2, padx=4)
ctrl_btn("Old Image", show_old).grid(row=0, column=3, padx=4)
ctrl_btn("New Image", show_new).grid(row=0, column=4, padx=4)

# STATUS
result_status = tk.Label(result_frame,
                         text="✅ Change Detection Done",
                         fg="green",
                         bg="#f5f6fa",
                         font=("Segoe UI", 10, "bold"))
result_status.pack(pady=10)

# BUTTONS
def big_btn(text, color, cmd):
    return tk.Button(result_frame,
                     text=text,
                     command=cmd,
                     bg=color,
                     fg="white",
                     font=("Segoe UI", 11, "bold"),
                     relief="flat",
                     height=2)

big_btn("⬇ Download TIFF", "#28a745", download_tif).pack(fill="x", padx=40, pady=5)
big_btn("⬇ Download ZIP", "#007bff", download_shp).pack(fill="x", padx=40, pady=5)
big_btn("➡ Go to Spatial Join", "#6f42c1", go_to_spatial).pack(fill="x", padx=40, pady=10)

tk.Button(result_frame,
          text="⬅ Back",
          command=go_back,
          bg="#dee2e6").pack(pady=10)



# -------- SPATIAL --------
# -------- SPATIAL (MODERN) --------
spatial_frame = tk.Frame(root, bg="#f5f6fa")

tk.Label(spatial_frame,
         text="🗺 Spatial Join Tool",
         font=("Segoe UI", 20, "bold"),
         bg="#f5f6fa").pack(pady=20)

# CARD
card = tk.Frame(spatial_frame, bg="white", width=400, height=280)
card.pack(pady=20)
card.pack_propagate(False)

auto_label = tk.Label(card, bg="white", fg="green", font=("Segoe UI", 10, "bold"))
auto_label.pack(pady=5)

tk.Label(card, text="Old Shapefile", bg="white",
         font=("Segoe UI", 12)).pack(pady=5)

old_shp_label = tk.Label(card, text="No file", bg="white", fg="gray")
old_shp_label.pack()

tk.Button(card,
          text="Choose File",
          command=load_old_shapefile,
          bg="#6c757d",
          fg="white",
          font=("Segoe UI", 10, "bold"),
          relief="flat").pack(pady=10)

tk.Button(card,
          text="🚀 Run Spatial Join",
          command=run_spatial_join,
          bg="black",
          fg="white",
          font=("Segoe UI", 11, "bold"),
          relief="flat",
          height=2).pack(pady=10)

spatial_status = tk.Label(spatial_frame,
                          text="",
                          fg="red",
                          bg="#f5f6fa",
                          font=("Segoe UI", 10))
spatial_status.pack()

tk.Button(spatial_frame,
          text="⬅ Back",
          command=lambda:[spatial_frame.pack_forget(),
                          result_frame.pack(fill="both", expand=True)],
          bg="#dee2e6").pack(pady=10)

# -------- SPATIAL RESULT --------
# -------- SPATIAL RESULT (MODERN UI) --------
spatial_result_frame = tk.Frame(root, bg="#f5f6fa")

tk.Label(spatial_result_frame, text="🗺 Spatial Join Result",
         font=("Arial", 20, "bold"),
         bg="#f5f6fa").pack(pady=15)

# ===== CARD CONTAINER =====
card_frame = tk.Frame(spatial_result_frame, bg="#f5f6fa")
card_frame.pack(pady=10)

def create_card(parent, title, color):
    frame = tk.Frame(parent, bg=color, width=180, height=100)
    frame.pack(side="left", padx=15)
    frame.pack_propagate(False)

    title_lbl = tk.Label(frame, text=title,
                         bg=color, fg="white",
                         font=("Arial", 12))
    title_lbl.pack(pady=5)

    value_lbl = tk.Label(frame, text="0",
                         bg=color, fg="white",
                         font=("Arial", 22, "bold"))
    value_lbl.pack()

    return value_lbl

total_label = create_card(card_frame, "Total", "#6c757d")
changed_label = create_card(card_frame, "Changed", "#28a745")
unchanged_label = create_card(card_frame, "Unchanged", "#dc3545")

# ===== BUTTONS =====
def styled_button(parent, text, color, command):
    btn = tk.Button(parent,
                    text=text,
                    bg=color,
                    fg="white",
                    font=("Arial", 12, "bold"),
                    relief="flat",
                    height=2,
                    command=command)
    btn.pack(fill="x", padx=40, pady=8)
    return btn

styled_button(spatial_result_frame, "Download Excel", "#218838", download_excel)
styled_button(spatial_result_frame, "Download Shapefile (ZIP)", "#1e66d0", download_spatial_zip)

tk.Button(spatial_result_frame, text="🔄 Run Again",
          font=("Arial", 11),
          command=lambda:[spatial_result_frame.pack_forget(),
                          upload_frame.pack(fill="both", expand=True)]
          ).pack(pady=15)

root.mainloop()