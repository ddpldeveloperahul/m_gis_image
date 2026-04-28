from celery import shared_task
from django.conf import settings
from django.core.files import File
from django.contrib.auth.models import User
import os, zipfile, shutil

from .utils import process_change, process_spatial_join
from .models import ChangeResult, SpatialJoinResult


# =========================
# 🔥 CHANGE DETECTION TASK
# =========================
@shared_task
def run_change_detection(img23_path, img25_path, user_id):
    from .views import build_preview_path, save_tiff_preview_png

    output_path = os.path.join(settings.MEDIA_ROOT, 'outputs')
    os.makedirs(output_path, exist_ok=True)

    # preview
    img23_png = build_preview_path(img23_path)
    img25_png = build_preview_path(img25_path)

    save_tiff_preview_png(img23_path, img23_png)
    save_tiff_preview_png(img25_path, img25_png)

    # main processing
    png, tif, zip_file = process_change(img23_path, img25_path, output_path)

    user = User.objects.get(id=user_id)
    obj = ChangeResult.objects.create(user=user)

    # save files
    with open(img23_path, 'rb') as f:
        obj.uploaded_2023.save(os.path.basename(img23_path), File(f), save=False)

    with open(img25_path, 'rb') as f:
        obj.uploaded_2025.save(os.path.basename(img25_path), File(f), save=False)

    with open(png, 'rb') as f:
        obj.result_png.save(os.path.basename(png), File(f), save=False)

    with open(tif, 'rb') as f:
        obj.result_tif.save(os.path.basename(tif), File(f), save=False)

    if zip_file and os.path.exists(zip_file):
        with open(zip_file, 'rb') as f:
            obj.result_shp.save(os.path.basename(zip_file), File(f), save=False)

    obj.save()

    return {"id": obj.id}


# =========================
# 🔥 SPATIAL JOIN TASK
# =========================
@shared_task
def run_spatial_join(main_zip_path, change_zip_path, user_id):

    base_dir = settings.MEDIA_ROOT
    work_dir = os.path.join(base_dir, 'spatial_work')
    main_dir = os.path.join(work_dir, 'main_extract')
    change_dir = os.path.join(work_dir, 'change_extract')
    output_dir = os.path.join(base_dir, 'spatial_output')

    if not os.path.exists(main_zip_path):
        raise FileNotFoundError(f"Old shapefile ZIP not found: {main_zip_path}")

    if not os.path.exists(change_zip_path):
        raise FileNotFoundError(f"Change shapefile ZIP not found: {change_zip_path}")

    # clean extraction folders only; do not delete uploaded ZIP folders
    for d in [main_dir, change_dir]:
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d)

    os.makedirs(output_dir, exist_ok=True)

    # unzip
    zipfile.ZipFile(main_zip_path).extractall(main_dir)
    zipfile.ZipFile(change_zip_path).extractall(change_dir)

    # find shp
    def find_shp(folder):
        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith('.shp'):
                    return os.path.join(root, file)
        return None

    main_shp = find_shp(main_dir)
    change_shp = find_shp(change_dir)

    if not main_shp or not change_shp:
        return {"error": "SHP not found"}

    # process
    result = process_spatial_join(main_shp, change_shp, output_dir)
    shp_zip_path = os.path.splitext(result['shapefile'])[0] + ".zip"
    with zipfile.ZipFile(shp_zip_path, "w") as archive:
        base, _ = os.path.splitext(result['shapefile'])
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            part = base + ext
            if os.path.exists(part):
                archive.write(part, os.path.basename(part))

    user = User.objects.get(id=user_id)
    obj = SpatialJoinResult.objects.create(user=user)

    obj.main_shapefile.save(os.path.basename(main_zip_path), File(open(main_zip_path, 'rb')))
    obj.change_shapefile.save(os.path.basename(change_zip_path), File(open(change_zip_path, 'rb')))

    obj.result_shapefile.save(os.path.basename(shp_zip_path), File(open(shp_zip_path, 'rb')))
    obj.result_excel.save(os.path.basename(result['excel']), File(open(result['excel'], 'rb')))

    obj.save()

    return {
        "id": obj.id,
        "total": result.get("total", 0),
        "changed": result.get("changed", 0),
        "unchanged": result.get("unchanged", 0),
    }
