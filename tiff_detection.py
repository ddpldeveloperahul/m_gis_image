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

# ================= FIXED IMAGE =================
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

    # ===== BLUE MAP =====
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

# ================= ZOOM (FIXED) =================
def update_zoom():
    if result_img is None:
        return

    base = 400
    new_size = int(base * scale)

    img = Image.fromarray(result_img)
    img = img.resize((new_size, new_size))  # 🔥 only image zoom

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

# ================= TOGGLE =================
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

# ================= UI =================
root = tk.Tk()
root.title("TIF Change Detection Tool")
root.geometry("800x700")

upload_frame = tk.Frame(root)
upload_frame.pack(fill="both", expand=True)

tk.Button(upload_frame, text="Load OLD TIF", command=load_old).pack(pady=5)
tk.Button(upload_frame, text="Load NEW TIF", command=load_new).pack(pady=5)

tk.Button(upload_frame, text="🚀 Run Change Detection",
          bg="blue", fg="white",
          command=show_result_page).pack(pady=10)

frame = tk.Frame(upload_frame)
frame.pack()

old_label = tk.Label(frame)
old_label.pack(side="left", padx=20)

new_label = tk.Label(frame)
new_label.pack(side="right", padx=20)

# ================= RESULT =================
result_frame = tk.Frame(root)

tk.Label(result_frame, text="Change Detection Result",
         font=("Arial", 16)).pack(pady=10)

# 🔥 FIXED BOX (IMPORTANT)
image_frame = tk.Frame(result_frame, width=400, height=400)
image_frame.pack()
image_frame.pack_propagate(False)

result_label = tk.Label(image_frame)
result_label.pack()

control = tk.Frame(result_frame)
control.pack()

tk.Button(control, text="Zoom In", command=zoom_in).grid(row=0,column=0,padx=5)
tk.Button(control, text="Zoom Out", command=zoom_out).grid(row=0,column=1,padx=5)
tk.Button(control, text="Reset", command=reset_zoom).grid(row=0,column=2,padx=5)
tk.Button(control, text="Back Image", command=show_old).grid(row=0,column=3,padx=5)
tk.Button(control, text="Front Image", command=show_new).grid(row=0,column=4,padx=5)

result_status = tk.Label(result_frame, fg="green")
result_status.pack()

tk.Button(result_frame, text="⬇ Download TIFF",
          bg="green", fg="white",
          command=download_tif).pack(pady=5)

tk.Button(result_frame, text="⬇ Download Shapefile (ZIP)",
          bg="blue", fg="white",
          command=download_shp).pack(pady=5)

tk.Button(result_frame, text="⬅ Back", command=go_back).pack(pady=10)

root.mainloop()