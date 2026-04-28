from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.conf import settings
from django.urls import reverse
from matplotlib import image
from requests import request
from .forms import ChangeResultForm, SpatialJoinForm
from .utils import process_change,process_spatial_join
import os
import json
import zipfile
import shutil
from .models import SpatialJoinResult,ChangeResult
from django.contrib.auth.models import User
from django.core.files import File
from django.views.decorators.csrf import csrf_exempt
from PIL import Image
from django.contrib.auth import authenticate, login, logout
from rest_framework.response import Response # type: ignore
from rest_framework import status # type: ignore
from myapp.serializers import SignupSerializer, LoginSerializer, SpatialJoinResultSerializer
from rest_framework.decorators import api_view, permission_classes # type: ignore
from rest_framework.permissions import IsAuthenticated # type: ignore
from django.http import JsonResponse
from .models import *
from datetime import timedelta
from rest_framework_simplejwt.tokens import RefreshToken # type: ignore
import numpy as np
from django.views.decorators.csrf import csrf_exempt
from  rest_framework.permissions import IsAuthenticated # type: ignore
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.plot import reshape_as_image
import cv2
from PIL import Image
import os
import geopandas as gpd
import pandas as pd
from urllib.parse import urlencode

def media_url_from_path(file_path):
    return settings.MEDIA_URL + os.path.relpath(file_path, settings.MEDIA_ROOT).replace("\\", "/")


def resolve_media_file_path(file_ref):
    if not file_ref:
        return None

    normalized_ref = str(file_ref).strip()

    if normalized_ref.startswith(settings.MEDIA_URL):
        normalized_ref = normalized_ref[len(settings.MEDIA_URL):]

    normalized_ref = normalized_ref.lstrip("/\\")

    if os.path.isabs(normalized_ref):
        candidate = os.path.abspath(normalized_ref)
    else:
        candidate = os.path.abspath(os.path.join(settings.MEDIA_ROOT, normalized_ref))

    media_root = os.path.abspath(settings.MEDIA_ROOT)

    try:
        common_path = os.path.commonpath([candidate, media_root])
    except ValueError:
        return None

    if common_path != media_root:
        return None

    return candidate if os.path.exists(candidate) else None


def build_download_url(route_name, file_name):
    return f"{reverse(route_name)}?{urlencode({'file': file_name})}"


def build_preview_path(source_path):
    base, _ = os.path.splitext(source_path)
    return base + ".png"


def normalize_band_to_uint8(band):
    finite_mask = np.isfinite(band)
    if not finite_mask.any():
        return np.zeros(band.shape, dtype=np.uint8)

    values = band[finite_mask].astype(np.float32)
    low, high = np.percentile(values, (2, 98))

    if high <= low:
        scaled = np.zeros(band.shape, dtype=np.uint8)
        scaled[finite_mask] = 255
        return scaled

    normalized = np.clip((band.astype(np.float32) - low) / (high - low), 0, 1)
    normalized[~finite_mask] = 0
    return (normalized * 255).astype(np.uint8)


def to_preview_rgb(data):
    if data.ndim == 2:
        data = data[np.newaxis, ...]

    if data.shape[0] >= 3:
        channels = data[:3]
    else:
        channels = np.repeat(data[:1], 3, axis=0)

    rgb = np.stack([normalize_band_to_uint8(channel) for channel in channels], axis=-1)
    return rgb

def save_tiff_preview_png(source_path, preview_path):
    import rasterio
    import numpy as np
    from PIL import Image
    from rasterio.enums import Resampling

    MAX_PREVIEW_SIZE = 1024
    
    with rasterio.open(source_path) as src:
        print(f"Image info: bands={src.count}, shape=({src.height}x{src.width}), dtype={src.dtypes[0]}")
        
        # Calculate scaling
        scale = max(src.width / MAX_PREVIEW_SIZE, src.height / MAX_PREVIEW_SIZE, 1)
        out_height = int(src.height / scale)
        out_width = int(src.width / scale)

        # Read first 3 bands or less
        band_count = min(3, src.count)
        data = src.read(list(range(1, band_count + 1)), out_shape=(band_count, out_height, out_width), resampling=Resampling.bilinear)
        
        print(f"Read {band_count} bands, shape: {data.shape}")

        # Convert to uint8 with proper normalization for satellite imagery
        if band_count == 1:
            # Single band → grayscale → RGB
            band = data[0].astype(np.float32)
            p2, p98 = np.percentile(band[np.isfinite(band)], (2, 98))
            normalized = np.clip((band - p2) / (p98 - p2 + 1e-6), 0, 1)
            normalized = (normalized * 255).astype(np.uint8)
            img = np.stack([normalized, normalized, normalized], axis=-1)
        else:
            # Multi-band → RGB
            img_data = data[:3].astype(np.float32)
            
            # Normalize each band independently for better color
            normalized_bands = []
            for i in range(img_data.shape[0]):
                band = img_data[i]
                p2, p98 = np.percentile(band[np.isfinite(band)], (2, 98))
                normalized = np.clip((band - p2) / (p98 - p2 + 1e-6), 0, 1)
                normalized_bands.append((normalized * 255).astype(np.uint8))
            
            # Stack as RGB (in correct order)
            img = np.stack(normalized_bands, axis=-1)
        
        print(f"Preview shape: {img.shape}, dtype: {img.dtype}")
        Image.fromarray(img, mode='RGB').save(preview_path)
        print(f"Preview saved: {preview_path}")

def build_result_context(result_png_path, result_tif_path, result_shp_path, img23_preview_path, img25_preview_path, img23_name, img25_name):
    return {
        'result_png': media_url_from_path(result_png_path),
        'result_tif': media_url_from_path(result_tif_path),
        'result_shp': media_url_from_path(result_shp_path),
        'img23': media_url_from_path(img23_preview_path),
        'img25': media_url_from_path(img25_preview_path),
        'img23_source': media_url_from_path(os.path.join(settings.MEDIA_ROOT, 'uploads', img23_name)),
        'img25_source': media_url_from_path(os.path.join(settings.MEDIA_ROOT, 'uploads', img25_name)),
        'result_shp_source': media_url_from_path(result_shp_path),
        'img23_name': img23_name,
        'img25_name': img25_name,
        'result_shp_name': os.path.basename(result_shp_path),
        'result_tif_name': os.path.basename(result_tif_path),
    }


def home(request):
    return render(request, 'base.html')


# def upload_images(request):

#     import os
#     from django.conf import settings
#     from django.core.files import File
#     from django.http import HttpResponse
#     from django.shortcuts import render
#     from django.contrib.auth.models import User

#     if request.method == 'POST':

#         form = ChangeResultForm(request.POST, request.FILES)

#         # year1 = request.POST.get('year1')
#         # year2 = request.POST.get('year2')

#         img23 = request.FILES.get('uploaded_2023')
#         img25 = request.FILES.get('uploaded_2025')

#         print("📥 RECEIVED:",img23, img25)

#         # =========================
#         # ✅ VALIDATION
#         # =========================
#         # if not year1 or not year2:
#         #     return HttpResponse("❌ Please select both years")

#         # if not img23 or not img25:
#         #     return HttpResponse("❌ Please upload both images")

#         # if not form.is_valid():
#         #     return HttpResponse("❌ Invalid form data")

#         try:
#             # =========================
#             # 📁 PATH SETUP
#             # =========================
#             upload_path = os.path.join(settings.MEDIA_ROOT, 'uploads')
#             output_path = os.path.join(settings.MEDIA_ROOT, 'outputs')

#             os.makedirs(upload_path, exist_ok=True)
#             os.makedirs(output_path, exist_ok=True)

#             img23_path = os.path.join(upload_path, img23.name)
#             img25_path = os.path.join(upload_path, img25.name)

#             # =========================
#             # 💾 SAVE FILES
#             # =========================
#             print("💾 Saving files...")

#             # Use shutil.copyfileobj for efficient large file handling
#             with open(img23_path, 'wb') as f:
#                 shutil.copyfileobj(img23.file, f, length=1024*1024)

#             with open(img25_path, 'wb') as f:
#                 shutil.copyfileobj(img25.file, f, length=1024*1024)

#             print("✅ Files saved")

#             # =========================
#             # 🖼️ PREVIEW
#             # =========================
#             print("🖼️ Generating preview...")

#             img23_png_path = build_preview_path(img23_path)
#             img25_png_path = build_preview_path(img25_path)

#             save_tiff_preview_png(img23_path, img23_png_path)
#             save_tiff_preview_png(img25_path, img25_png_path)

#             print("✅ Preview created")

#             # =========================
#             # 🚀 PROCESS CHANGE
#             # =========================
#             print("🚀 Processing started (FAST MODE)...")

#             png, tif, zip_file = process_change(
#                 img23_path,
#                 img25_path,
#                 output_path,
        
#             )

#             print("✅ Processing completed")

#             # =========================
#             # 💾 SAVE TO DATABASE
#             # =========================
#             user = request.user if request.user.is_authenticated else User.objects.first()

#             obj = ChangeResult.objects.create(user=user)

#             print("💾 Saving results to DB...")

#             # input images
#             with open(img23_path, 'rb') as f:
#                 obj.uploaded_2023.save(img23.name, File(f), save=False)

#             with open(img25_path, 'rb') as f:
#                 obj.uploaded_2025.save(img25.name, File(f), save=False)

#             # outputs
#             with open(png, 'rb') as f:
#                 obj.result_png.save(os.path.basename(png), File(f), save=False)

#             with open(tif, 'rb') as f:
#                 obj.result_tif.save(os.path.basename(tif), File(f), save=False)

#             # ✅ SAFE SHP SAVE - Only save if zip file exists
#             if zip_file is not None and os.path.exists(zip_file):
#                 with open(zip_file, 'rb') as f:
#                     obj.result_shp.save(os.path.basename(zip_file), File(f), save=False)
#                 print(f"✅ Shapefile saved: {os.path.basename(zip_file)}")
#             else:
#                 print("⚠️ No shapefile created (no changes detected or empty result)")

#             obj.save()

#             print("✅ Saved to DB")

#             # =========================
#             # 🎯 RESPONSE
#             # =========================
#             context = {
#                 'result_png': media_url_from_path(png),
#                 'result_tif': media_url_from_path(tif),
#                 'result_shp': media_url_from_path(zip_file) if zip_file else None,
#                 'img23': media_url_from_path(img23_png_path),
#                 'img25': media_url_from_path(img25_png_path),
#                 'img23_name': img23.name,
#                 'img25_name': img25.name,
#             }

#             return render(request, 'result.html', context)

#         except Exception as e:
#             import traceback
#             error_msg = str(e) if str(e) else type(e).__name__
#             traceback.print_exc()
#             print("❌ ERROR:", error_msg)
#             return HttpResponse(f"❌ Error: {error_msg}")

#     # =========================
#     # GET REQUEST
#     # =========================
#     form = ChangeResultForm()
#     years = list(range(2000, 2027))

#     return render(request, 'upload.html', {
#         'form': form,
#         'years': years
#     })

from .tasks import run_change_detection
from .file_handler import save_large_file


@csrf_exempt
def upload_chunk(request):
    """Handle chunked file uploads from Resumable.js"""
    try:
        print(f"Upload chunk called - Method: {request.method}")
        print(f"POST data: {request.POST}")
        print(f"FILES: {request.FILES}")
        
        if request.method == 'POST':
            # Resumable.js sends the file with name 'file'
            chunk_file = request.FILES.get('file')
            
            if not chunk_file:
                print("No 'file' in request.FILES")
                # Try alternative field names
                for key in request.FILES:
                    print(f"Available file key: {key}")
                    chunk_file = request.FILES.get(key)
                    if chunk_file:
                        break
            
            if not chunk_file:
                print("Error: No file provided")
                return JsonResponse({'error': 'No file provided'}, status=400)
            
            print(f"Saving file: {chunk_file.name}")
            # Save the uploaded file
            file_path = save_large_file(chunk_file, "uploads")
            print(f"File saved at: {file_path}")
            
            return JsonResponse({
                'file_path': file_path,
                'message': 'File uploaded successfully'
            })
        
        # GET request for checking if chunk exists (optional)
        return JsonResponse({'status': 'ready'})
    except Exception as e:
        print(f"Upload chunk error: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return JsonResponse({
            'error': f"Upload error: {str(e)}"
        }, status=500)


def upload_images(request):

    if request.method == 'POST':

        file1 = request.FILES.get('uploaded_2023')
        file2 = request.FILES.get('uploaded_2025')

        if not file1 or not file2:
            return JsonResponse({'error': 'Files missing'}, status=400)

        path1 = save_large_file(file1, "uploads")
        path2 = save_large_file(file2, "uploads")

        user = request.user if request.user.is_authenticated else User.objects.first()

        # 🔥 FIX: user_id pass karo
        task = run_change_detection.delay(path1, path2, user.id)

        return render(request, "processing.html", {
            "task_id": task.id
        })

    return render(request, 'upload.html')


def result_view(request):
    result_id = request.GET.get('id')

    if not result_id:
        return HttpResponse("Result id is required", status=400)

    try:
        result = ChangeResult.objects.get(id=result_id)
    except ChangeResult.DoesNotExist:
        return HttpResponse("Result not found", status=404)

    def field_path(field):
        try:
            return field.path if field else None
        except ValueError:
            return None

    result_png_path = field_path(result.result_png)
    result_tif_path = field_path(result.result_tif)
    result_shp_path = field_path(result.result_shp)
    img23_path = field_path(result.uploaded_2023)
    img25_path = field_path(result.uploaded_2025)
    img23_preview_path = build_preview_path(img23_path) if img23_path else None
    img25_preview_path = build_preview_path(img25_path) if img25_path else None

    for source_path, preview_path in (
        (img23_path, img23_preview_path),
        (img25_path, img25_preview_path),
    ):
        if source_path and preview_path and not os.path.exists(preview_path):
            save_tiff_preview_png(source_path, preview_path)

    context = {
        'result_png': media_url_from_path(result_png_path) if result_png_path else '',
        'result_tif': media_url_from_path(result_tif_path) if result_tif_path else '',
        'result_shp': media_url_from_path(result_shp_path) if result_shp_path else '',
        'img23': media_url_from_path(img23_preview_path) if img23_preview_path and os.path.exists(img23_preview_path) else '',
        'img25': media_url_from_path(img25_preview_path) if img25_preview_path and os.path.exists(img25_preview_path) else '',
        'img23_source': media_url_from_path(img23_path) if img23_path else '',
        'img25_source': media_url_from_path(img25_path) if img25_path else '',
        'result_shp_source': media_url_from_path(result_shp_path) if result_shp_path else '',
        'img23_name': os.path.basename(result.uploaded_2023.name) if result.uploaded_2023 else '',
        'img25_name': os.path.basename(result.uploaded_2025.name) if result.uploaded_2025 else '',
        'result_shp_name': os.path.basename(result.result_shp.name) if result.result_shp else '',
        'result_tif_name': os.path.basename(result.result_tif.name) if result.result_tif else '',
    }

    return render(request, 'result.html', context)






# def spatial_join_view(request):
#     prefilled_file = request.GET.get('file')
#     file_name = os.path.basename(prefilled_file) if prefilled_file else None

#     if request.method == 'POST':

#         prefilled_file = request.POST.get('prefilled_file')
#         main_zip = request.FILES.get('main_zip')
#         change_zip = request.FILES.get('change_zip')

#         base_dir = settings.MEDIA_ROOT
#         main_dir = os.path.join(base_dir, 'main')
#         change_dir = os.path.join(base_dir, 'change')
#         output_dir = os.path.join(base_dir, 'spatial_output')

#         # Clean old folders
#         for d in [main_dir, change_dir]:
#             if os.path.exists(d):
#                 shutil.rmtree(d)
#             os.makedirs(d)

#         os.makedirs(output_dir, exist_ok=True)

#         # =========================
#         # MAIN ZIP
#         # =========================
#         if main_zip:
#             main_zip_path = os.path.join(main_dir, main_zip.name)

#             with open(main_zip_path, 'wb+') as f:
#                 for chunk in main_zip.chunks():
#                     f.write(chunk)

#             zipfile.ZipFile(main_zip_path).extractall(main_dir)
#         else:
#             return HttpResponse("Please upload main shapefile ZIP")

#         # =========================
#         # CHANGE ZIP
#         # =========================
#         if not change_zip and prefilled_file:
#             change_zip_path = os.path.join(
#                 settings.BASE_DIR,
#                 prefilled_file.replace('/media/', 'media/')
#             )

#             if not os.path.exists(change_zip_path):
#                 return HttpResponse("Auto shapefile not found")

#         elif change_zip:
#             change_zip_path = os.path.join(change_dir, change_zip.name)

#             with open(change_zip_path, 'wb+') as f:
#                 for chunk in change_zip.chunks():
#                     f.write(chunk)

#         else:
#             return HttpResponse("Change shapefile missing")

#         zipfile.ZipFile(change_zip_path).extractall(change_dir)

#         # =========================
#         # FIND SHP FILE
#         # =========================
#         def find_shp(folder):
#             for root, dirs, files in os.walk(folder):
#                 for file in files:
#                     if file.lower().endswith('.shp'):
#                         return os.path.join(root, file)
#             return None

#         main_shp = find_shp(main_dir)
#         change_shp = find_shp(change_dir)

#         if not main_shp:
#             return HttpResponse(".shp not found in main ZIP")

#         if not change_shp:
#             return HttpResponse(".shp not found in change ZIP")

#         # =========================
#         # PROCESS
#         # =========================
#         try:
#             result = process_spatial_join(main_shp, change_shp, output_dir)
#         except Exception as e:
#             return HttpResponse(f"Processing Error: {str(e)}")

#         # =========================
#         # SAVE TO DATABASE
#         # =========================
#         user = request.user if request.user.is_authenticated else User.objects.first()

#         obj = SpatialJoinResult.objects.create(user=user)

#         # Save input files
#         obj.main_shapefile.save(main_zip.name, File(open(main_zip_path, 'rb')))

#         if change_zip:
#             obj.change_shapefile.save(change_zip.name, File(open(change_zip_path, 'rb')))
#         else:
#             obj.change_shapefile.name = prefilled_file.replace('/media/', '')

#         # Save outputs
#         obj.result_shapefile.save(
#             os.path.basename(result['shapefile']),
#             File(open(result['shapefile'], 'rb'))
#         )

#         obj.result_excel.save(
#             os.path.basename(result['excel']),
#             File(open(result['excel'], 'rb'))
#         )

#         obj.save()

#         return render(request, 'result1.html', {
#             'result': result,
#             'excel_url': obj.result_excel.url,
#             'shp_url': obj.result_shapefile.url,
#             'excel_download_url': build_download_url('download_excel', obj.result_excel.name),
#             'shp_download_url': build_download_url('download_shapefile', obj.result_shapefile.name),
#         })

#     return render(request, 'change.html', {
#         'prefilled_file': prefilled_file,
#         'file_name': file_name
#     })


from django.http import FileResponse
import zipfile

def render_spatial_join_result(request, result_id):
    try:
        obj = SpatialJoinResult.objects.get(id=result_id)
    except SpatialJoinResult.DoesNotExist:
        return HttpResponse("Spatial join result not found", status=404)

    def get_stats_from_excel(excel_path):
        stats = {
            'total': 0,
            'changed': 0,
            'unchanged': 0,
        }

        if not excel_path or not os.path.exists(excel_path):
            return stats

        try:
            excel_df = pd.read_excel(excel_path, sheet_name='All Data')
        except Exception:
            return stats

        stats['total'] = len(excel_df)

        if 'changed' in excel_df.columns:
            changed_values = excel_df['changed'].astype(str).str.upper()
            stats['changed'] = int((changed_values == 'YES').sum())
            stats['unchanged'] = int((changed_values == 'NO').sum())
        elif 'changed_flag' in excel_df.columns:
            changed_values = excel_df['changed_flag'].astype(bool)
            stats['changed'] = int(changed_values.sum())
            stats['unchanged'] = int(stats['total'] - stats['changed'])
        else:
            stats['unchanged'] = stats['total']

        return stats

    stats = get_stats_from_excel(obj.result_excel.path)

    result = {
        **stats,
        'shapefile': obj.result_shapefile.path,
        'excel': obj.result_excel.path,
    }

    return render(request, 'result1.html', {
        'result': result,
        'excel_url': obj.result_excel.url,
        'shp_url': obj.result_shapefile.url,
        'excel_download_url': build_download_url('download_excel', obj.result_excel.name),
        'shp_download_url': build_download_url('download_shapefile', obj.result_shapefile.name),
    })

def download_excel(request):
    file_path = resolve_media_file_path(request.GET.get('file'))

    if not file_path:
        return HttpResponse("File not found", status=404)

    return FileResponse(
        open(file_path, 'rb'),
        as_attachment=True,
        filename=os.path.basename(file_path)
    )

def download_shapefile(request):
    shp_path = resolve_media_file_path(request.GET.get('file'))

    if not shp_path:
        return HttpResponse("File not found", status=404)

    if shp_path.lower().endswith(".zip"):
        return FileResponse(
            open(shp_path, 'rb'),
            as_attachment=True,
            filename=os.path.basename(shp_path)
        )

    base = os.path.splitext(shp_path)[0]
    zip_path = base + ".zip"

    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
            f = base + ext
            if os.path.exists(f):
                zipf.write(f, os.path.basename(f))

    return FileResponse(open(zip_path, 'rb'), as_attachment=True)




from .tasks import run_spatial_join

def spatial_join_view(request):
    prefilled_file = request.GET.get('file') or request.POST.get('prefilled_file')
    prefilled_path = resolve_media_file_path(prefilled_file)
    file_name = os.path.basename(prefilled_path) if prefilled_path else None

    if request.method == 'POST':

        main_zip = request.FILES.get('main_zip')
        change_zip = request.FILES.get('change_zip')

        if not main_zip:
            return HttpResponse("Upload old shapefile ZIP file", status=400)

        if not change_zip and not prefilled_path:
            return HttpResponse("Change shapefile file not found. Please select it again.", status=400)

        main_path = save_large_file(main_zip, "main")
        change_path = save_large_file(change_zip, "change") if change_zip else prefilled_path

        user = request.user if request.user.is_authenticated else User.objects.first()
        if user is None:
            return HttpResponse("No user found. Please create or log in as a user first.", status=400)

        task = run_spatial_join.delay(main_path, change_path, user.id)

        if isinstance(task, EagerResult) and task.successful():
            result_id = task.result.get("id") if isinstance(task.result, dict) else None
            if result_id:
                return render_spatial_join_result(request, result_id)
            if isinstance(task.result, dict) and task.result.get("error"):
                return HttpResponse(task.result["error"], status=400)

        if isinstance(task, EagerResult) and task.failed():
            return HttpResponse(str(task.result), status=500)

        return render(request, "processing.html", {
            "task_id": task.id
        })

    return render(request, 'change.html', {
        'prefilled_file': prefilled_file if prefilled_path else None,
        'file_name': file_name,
        'prefilled_error': "Selected change file was not found. Please run change detection again." if prefilled_file and not prefilled_path else None,
    })
# ✅ SIGNUP
@api_view(['POST'])
def signup_api(request):
    data = request.data.copy()
    data = {k: v for k, v in data.items()}  # force normal dict

    if not data.get('username'):
        data['username'] = data.get('name') or data.get('usenama')

    if not data.get('password'):
        data['password'] = data.get('passwod')

    if not data.get('confirm_password'):
        data['confirm_password'] = (
            data.get('confirm-passowd') or
            data.get('confirm_passowd')
        )

    print("FINAL DATA:", data)  # debug

    serializer = SignupSerializer(data=data)

    if serializer.is_valid():
        user = serializer.save()
        return Response({
            "message": "User created successfully",
            "user_id": user.id
        })

    return Response(serializer.errors, status=400)
@api_view(['POST'])
def login_api(request):

    username = request.data.get('username')
    password = request.data.get('password')

    user = authenticate(username=username, password=password)

    if user is None:
        return Response({"error": "Invalid credentials"}, status=401)

    refresh = RefreshToken.for_user(user)

    return Response({
        "message": "Login successful",
        "access_token": str(refresh.access_token),
        "refresh_token": str(refresh)
    })

# ✅ LOGOUT
@api_view(['POST'])
def logout_api(request):
    return Response({"message": "Logout successful (client should delete token)"})


def logout_view(request):
    """Handle HTML form logout and redirect to login page"""
    logout(request)
    return redirect('login')


@csrf_exempt
@api_view(['GET'])
def list_excel_files(request):
    results = [
        result
        for result in SpatialJoinResult.objects.all().order_by('-created_at')
        if result.result_excel and result.result_excel.storage.exists(result.result_excel.name)
    ]
    serializer = SpatialJoinResultSerializer(results, many=True, context={'request': request})
    return Response(serializer.data)

def login_page(request):
    if request.user.is_authenticated:
        return redirect('upload') 
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            return redirect('upload')
        else:
            return render(request, 'login.html', {'error': 'Invalid credentials'})
    
    return render(request, 'login.html')

def signup_page(request):
    return render(request, 'signup.html')

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from celery.result import EagerResult
from .tasks import run_change_detection

@csrf_exempt
@csrf_exempt
def start_processing(request):
    try:
        # Log request details for debugging
        print(f"Request method: {request.method}")
        print(f"Request body: {request.body}")
        print(f"Content-Type: {request.META.get('CONTENT_TYPE')}")
        
        if not request.body:
            return JsonResponse({
                "error": "Request body is empty"
            }, status=400)
        
        data = json.loads(request.body)
        print(f"Parsed data: {data}")
        
        file1 = data.get('file1')
        file2 = data.get('file2')
        
        print(f"file1: {file1}, file2: {file2}")
        
        if not file1 or not file2:
            return JsonResponse({
                "error": f"file1 and file2 are required. Received: file1={file1}, file2={file2}"
            }, status=400)

        # ⚠️ agar 2 file hain toh dono pass karo (modify accordingly)
        user = request.user if request.user.is_authenticated else User.objects.first()
        if user is None:
            return JsonResponse({
                "error": "No user found. Please create or log in as a user first."
            }, status=400)

        task = run_change_detection.delay(file1, file2, user.id)

        response = {"task_id": task.id}
        if isinstance(task, EagerResult) and task.successful():
            response.update({
                "status": "SUCCESS",
                "result": task.result,
            })

        return JsonResponse(response)
    except json.JSONDecodeError as e:
        return JsonResponse({
            "error": f"Invalid JSON: {str(e)}"
        }, status=400)
    except Exception as e:
        import traceback
        print(f"Exception: {traceback.format_exc()}")
        return JsonResponse({
            "error": f"Error: {str(e)}"
        }, status=500)


@csrf_exempt
def task_status(request, task_id):
    """Get the status of a Celery task"""
    from celery.result import AsyncResult
    
    print(f"Task status request for task_id: {task_id}")
    
    if not task_id or task_id == 'undefined':
        return JsonResponse({
            "error": "Invalid task_id"
        }, status=400)
    
    try:
        result = AsyncResult(task_id)
        response = {
            "task_id": task_id,
            "status": result.status,
        }
        
        if result.status == 'SUCCESS':
            response['result'] = result.result
        elif result.status == 'FAILURE':
            response['error'] = str(result.info)
        
        return JsonResponse(response)
    except Exception as e:
        import traceback
        print(f"Exception in task_status: {traceback.format_exc()}")
        return JsonResponse({
            "error": f"Error fetching task status: {str(e)}"
        }, status=500)
