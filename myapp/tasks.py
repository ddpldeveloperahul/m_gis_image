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
# @shared_task
# def run_change_detection(img23_path, img25_path, user_id):
#     from .views import build_preview_path, save_tiff_preview_png

#     output_path = os.path.join(settings.MEDIA_ROOT, 'outputs')
#     os.makedirs(output_path, exist_ok=True)

#     # preview
#     img23_png = build_preview_path(img23_path)
#     img25_png = build_preview_path(img25_path)

#     save_tiff_preview_png(img23_path, img23_png)
#     save_tiff_preview_png(img25_path, img25_png)

#     # main processing
#     png, tif, zip_file = process_change(img23_path, img25_path, output_path)

#     user = User.objects.get(id=user_id)
#     obj = ChangeResult.objects.create(user=user)

#     # save files
#     with open(img23_path, 'rb') as f:
#         obj.uploaded_2023.save(os.path.basename(img23_path), File(f), save=False)

#     with open(img25_path, 'rb') as f:
#         obj.uploaded_2025.save(os.path.basename(img25_path), File(f), save=False)

#     with open(png, 'rb') as f:
#         obj.result_png.save(os.path.basename(png), File(f), save=False)

#     with open(tif, 'rb') as f:
#         obj.result_tif.save(os.path.basename(tif), File(f), save=False)

#     if zip_file and os.path.exists(zip_file):
#         with open(zip_file, 'rb') as f:
#             obj.result_shp.save(os.path.basename(zip_file), File(f), save=False)

#     obj.save()

#     return {"id": obj.id}

@shared_task(bind=True)
def run_change_detection(self, img23_path, img25_path, user_id, job_id):

    from .views import build_preview_path, save_tiff_preview_png
    from .utils import process_change

    job = ChangeResult.objects.get(id=job_id)

    try:
        # 🔄 START PROCESS
        job.status = "processing"
        job.save(update_fields=["status"])

        output_path = os.path.join(settings.MEDIA_ROOT, 'outputs')
        os.makedirs(output_path, exist_ok=True)

        media_root = os.path.abspath(settings.MEDIA_ROOT)
        for field_name, file_path in (
            ("uploaded_2023", img23_path),
            ("uploaded_2025", img25_path),
        ):
            abs_path = os.path.abspath(file_path)
            if os.path.commonpath([media_root, abs_path]) == media_root:
                getattr(job, field_name).name = os.path.relpath(abs_path, media_root).replace("\\", "/")

        # =========================
        # 🖼 PREVIEW GENERATION
        # =========================
        img23_png = build_preview_path(img23_path)
        img25_png = build_preview_path(img25_path)

        save_tiff_preview_png(img23_path, img23_png)
        save_tiff_preview_png(img25_path, img25_png)

        # =========================
        # 🔥 MAIN PROCESS
        # =========================
        png, tif, zip_file = process_change(img23_path, img25_path, output_path)

        # =========================
        # 💾 SAVE OUTPUT FILES
        # =========================
        with open(png, 'rb') as f:
            job.result_png.save(os.path.basename(png), File(f), save=False)

        with open(tif, 'rb') as f:
            job.result_tif.save(os.path.basename(tif), File(f), save=False)

        if zip_file and os.path.exists(zip_file):
            with open(zip_file, 'rb') as f:
                job.result_shp.save(os.path.basename(zip_file), File(f), save=False)

        # =========================
        # ✅ COMPLETE (UNLOCK)
        # =========================
        job.status = "done"
        job.save()

        return {"status": "done", "id": job.id, "job_id": job.id}

    except Exception as e:
        import traceback
        print(traceback.format_exc())

        # =========================
        # ❌ FAIL (UNLOCK)
        # =========================
        job.status = "failed"
        job.save()

        raise e
    
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
    # Use safer cleanup to avoid permission errors
    def safe_remove_tree(path):
        """Safely remove directory tree, handling permission issues"""
        try:
            if os.path.exists(path):
                import stat
                def handle_remove_readonly(func, path, exc):
                    if not os.access(path, os.W_OK):
                        os.chmod(path, stat.S_IWUSR | stat.S_IREAD)
                        func(path)
                    else:
                        raise
                shutil.rmtree(path, onerror=handle_remove_readonly)
        except Exception as e:
            print(f"Warning: Could not fully clean {path}: {e}")
    
    for d in [main_dir, change_dir]:
        safe_remove_tree(d)
        os.makedirs(d, exist_ok=True)

    os.makedirs(output_dir, exist_ok=True)

    # unzip
    zipfile.ZipFile(main_zip_path).extractall(main_dir)
    zipfile.ZipFile(change_zip_path).extractall(change_dir)

    # find all shapefiles (to support multiple layers)
    def find_all_shp(folder):
        """Find all .shp files in folder (handles nested and wrapped ZIP structures)"""
        shp_files = []
        
        # Look for .shp files recursively
        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith('.shp'):
                    shp_files.append(os.path.join(root, file))
        
        # If no .shp files found and folder has only one subfolder, search in that subfolder
        if not shp_files:
            contents = os.listdir(folder)
            subdirs = [d for d in contents if os.path.isdir(os.path.join(folder, d))]
            if len(subdirs) == 1:
                nested_dir = os.path.join(folder, subdirs[0])
                for root, _, files in os.walk(nested_dir):
                    for file in files:
                        if file.lower().endswith('.shp'):
                            shp_files.append(os.path.join(root, file))
        
        return shp_files if shp_files else None

    main_shp_list = find_all_shp(main_dir)
    change_shp_list = find_all_shp(change_dir)

    if not main_shp_list:
        main_contents = os.listdir(main_dir) if os.path.exists(main_dir) else []
        return {"error": f"SHP not found in main shapefile. Found: {main_contents}"}
    
    if not change_shp_list:
        change_contents = os.listdir(change_dir) if os.path.exists(change_dir) else []
        return {"error": f"SHP not found in change shapefile. Found: {change_contents}"}
    
    # Use directories for multi-layer support
    # process_spatial_join will automatically merge all shapefiles in the directory
    # process
    result = process_spatial_join(main_dir, change_dir, output_dir)
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
