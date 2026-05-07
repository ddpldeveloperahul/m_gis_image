from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.conf import settings
from django.urls import reverse
from matplotlib import image
from requests import request
import os
import json
import zipfile
from .models import SpatialJoinResult,ChangeResult
from django.contrib.auth.models import User
from django.core.files import File
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from rest_framework.response import Response # type: ignore
from rest_framework import status # type: ignore
from myapp.serializers import SignupSerializer, LoginSerializer, SpatialJoinResultSerializer
from rest_framework.decorators import api_view # type: ignore
from django.db import transaction
from django.utils import timezone
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
from celery.result import EagerResult # type: ignore
from django.contrib.sessions.models import Session
from .tasks import run_change_detection
from .file_handler import save_large_file
from django.http import FileResponse
import zipfile
from .tasks import run_spatial_join

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


def build_aligned_preview_path(source_path):
    base, _ = os.path.splitext(source_path)
    return base + "_aligned_to_old.png"


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


def save_aligned_tiff_preview_png(reference_path, source_path, preview_path):
    from PIL import Image
    from rasterio.enums import Resampling
    from .utils import open_aligned_new_source

    MAX_PREVIEW_SIZE = 1024

    with rasterio.open(reference_path) as reference_src, rasterio.open(source_path) as source_src:
        with open_aligned_new_source(reference_src, source_src) as aligned_src:
            scale = max(aligned_src.width / MAX_PREVIEW_SIZE, aligned_src.height / MAX_PREVIEW_SIZE, 1)
            out_height = max(1, int(aligned_src.height / scale))
            out_width = max(1, int(aligned_src.width / scale))
            band_count = min(3, aligned_src.count)
            data = aligned_src.read(
                list(range(1, band_count + 1)),
                out_shape=(band_count, out_height, out_width),
                resampling=Resampling.bilinear,
            )

        img = to_preview_rgb(data)
        Image.fromarray(img, mode='RGB').save(preview_path)
        print(f"Aligned preview saved: {preview_path}")

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


@csrf_exempt
def processing_availability(request):
    running_job = get_active_change_job()

    if running_job:
        username = running_job.user.username if running_job.user else "another user"
        return JsonResponse({
            "available": False,
            "error": f"Server busy. {username}'s change detection is already processing. Please wait until it finishes."
        }, status=429)

    return JsonResponse({"available": True})


@csrf_exempt
def upload_chunk(request):
    """Handle chunked file uploads from Resumable.js"""
    try:
        print(f"Upload chunk called - Method: {request.method}")
        print(f"POST data: {request.POST}")
        print(f"FILES: {request.FILES}")

        user = request.user if request.user.is_authenticated else User.objects.first()
        clear_inactive_processing_jobs()
        clear_inactive_processing_jobs()

        if request.method == 'POST':
            running_job = get_active_change_job()
            if running_job:
                username = running_job.user.username if running_job.user else "another user"
                return JsonResponse({
                    'error': f"Server busy. {username}'s change detection is already processing. Please wait until it finishes."
                }, status=429)
        
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
            file_path = save_large_file(chunk_file, "uploads", user=user)
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


def get_logged_in_user_ids():
    user_ids = set()
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        user_id = session.get_decoded().get("_auth_user_id")
        if user_id:
            user_ids.add(int(user_id))
    return user_ids


def clear_inactive_processing_jobs():
    stale_before = timezone.now() - timedelta(minutes=30)
    ChangeResult.objects.filter(status="processing", created_at__lt=stale_before).update(status="failed")
    active_user_ids = get_logged_in_user_ids()
    if active_user_ids:
        ChangeResult.objects.filter(status="processing").exclude(user_id__in=active_user_ids).update(status="failed")
    else:
        ChangeResult.objects.filter(status="processing").update(status="failed")


def get_active_change_job():
    clear_inactive_processing_jobs()
    return ChangeResult.objects.filter(status="processing").select_related("user").first()


def upload_images(request):

    if request.method == 'POST':

        user = request.user if request.user.is_authenticated else User.objects.first()

        # 🔒 LOCK FIRST (before anything)
        with transaction.atomic():

            running_job = ChangeResult.objects.select_for_update().filter(status="processing").select_related("user").first()

            if running_job:
                username = running_job.user.username if running_job.user else "another user"
                return JsonResponse({
                    'error': '⚠️ Server busy. Please wait.'
                }, status=429)

            # ✅ job create immediately (lock acquired)
            job = ChangeResult.objects.create(
                user=user,
                status="processing"
            )

        # ⬇️ now file handling
        file1 = request.FILES.get('uploaded_2023')
        file2 = request.FILES.get('uploaded_2025')

        if not file1 or not file2:
            job.status = "failed"
            job.save()
            return JsonResponse({'error': 'Files missing'}, status=400)

        path1 = save_large_file(file1, "uploads", user=user)
        path2 = save_large_file(file2, "uploads", user=user)

        # 🚀 celery
        run_change_detection.delay(path1, path2, user.id, job.id)

        return JsonResponse({
            "message": "Processing started",
            "job_id": job.id
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
    img25_preview_path = build_aligned_preview_path(img25_path) if img23_path and img25_path else (
        build_preview_path(img25_path) if img25_path else None
    )

    if img23_path and img23_preview_path and not os.path.exists(img23_preview_path):
        save_tiff_preview_png(img23_path, img23_preview_path)

    if img23_path and img25_path and img25_preview_path and not os.path.exists(img25_preview_path):
        save_aligned_tiff_preview_png(img23_path, img25_path, img25_preview_path)
    elif img25_path and img25_preview_path and not os.path.exists(img25_preview_path):
        save_tiff_preview_png(img25_path, img25_preview_path)

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
    if request.user.is_authenticated:
        ChangeResult.objects.filter(user=request.user, status="processing").update(status="failed")
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

@csrf_exempt
def start_processing(request):
    try:
        if not request.body:
            return JsonResponse({"error": "Request body is empty"}, status=400)

        data = json.loads(request.body)

        file1 = data.get('file1')
        file2 = data.get('file2')

        if not file1 or not file2:
            return JsonResponse({"error": "file1 and file2 are required"}, status=400)

        user = request.user if request.user.is_authenticated else User.objects.first()

        clear_inactive_processing_jobs()

        if user is None:
            return JsonResponse({"error": "No user found"}, status=400)

        # 🔒 ATOMIC LOCK (IMPORTANT)
        with transaction.atomic():

            running_job = ChangeResult.objects.select_for_update().filter(status="processing").select_related("user").first()

            if running_job:
                username = running_job.user.username if running_job.user else "another user"
                return JsonResponse({
                    "error": f"Server busy. {username}'s change detection is already processing. Please wait until it finishes."
                }, status=429)
                return JsonResponse({
                    "error": "⚠️ Server busy. Please wait until current processing finishes."
                }, status=429)

            # ✅ create job
            job = ChangeResult.objects.create(
                user=user,
                status="processing"
            )

        # 🚀 Celery call (outside transaction)
        task = run_change_detection.delay(file1, file2, user.id, job.id)

        return JsonResponse({
            "task_id": task.id,
            "job_id": job.id
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)


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
