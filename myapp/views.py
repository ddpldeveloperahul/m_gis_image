from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.conf import settings
from requests import request
from myapp.decorators import subscription_required
from .forms import ChangeResultForm, SpatialJoinForm
from .utils import process_change,process_spatial_join
import os
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
from .decorators import subscription_required

from rest_framework.decorators import api_view, permission_classes # type: ignore
from rest_framework.permissions import IsAuthenticated # type: ignore
from django.http import JsonResponse
from .models import *
from .payment import create_order
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

def media_url_from_path(file_path):
    return settings.MEDIA_URL + os.path.relpath(file_path, settings.MEDIA_ROOT).replace("\\", "/")


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


def save_tiff_preview_png(source_path, preview_path, reference_path=None):
    with rasterio.open(source_path) as src:
        if reference_path:
            with rasterio.open(reference_path) as ref:
                band_count = min(max(src.count, 1), 3)
                aligned = np.zeros((band_count, ref.height, ref.width), dtype=np.float32)

                for band_index in range(band_count):
                    reproject(
                        source=rasterio.band(src, band_index + 1),
                        destination=aligned[band_index],
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=ref.transform,
                        dst_crs=ref.crs,
                        resampling=Resampling.bilinear,
                    )

                preview_rgb = to_preview_rgb(aligned)
        else:
            preview_rgb = to_preview_rgb(src.read())

    Image.fromarray(preview_rgb).save(preview_path)


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


# @subscription_required
# def upload_images(request):
#     if request.method == 'POST':
#         form = ChangeResultForm(request.POST, request.FILES)

#         year1 = request.POST.get('year1')
#         year2 = request.POST.get('year2')

#         img23 = request.FILES.get('uploaded_2023')
#         img25 = request.FILES.get('uploaded_2025')

#         # ✅ Validation
#         if not year1 or not year2:
#             return HttpResponse("❌ Please select both years")

#         if not img23 or not img25:
#             return HttpResponse("❌ Please upload both images")

#         if form.is_valid():

#             # ✅ IMPORTANT: PATH DEFINE KARO
#             upload_path = os.path.join(settings.MEDIA_ROOT, 'uploads')
#             output_path = os.path.join(settings.MEDIA_ROOT, 'outputs')

#             os.makedirs(upload_path, exist_ok=True)
#             os.makedirs(output_path, exist_ok=True)

#             img23_path = os.path.join(upload_path, img23.name)
#             img25_path = os.path.join(upload_path, img25.name)

#             # ✅ SAVE FILES
#             with open(img23_path, 'wb+') as f:
#                 for chunk in img23.chunks():
#                     f.write(chunk)

#             with open(img25_path, 'wb+') as f:
#                 for chunk in img25.chunks():
#                     f.write(chunk)

#             # 🔥 TIF → PNG
#             import rasterio
#             from rasterio.plot import reshape_as_image
#             import cv2
#             import numpy as np

#             # with rasterio.open(img23_path) as src:
#             #     img = reshape_as_image(src.read())
#             #     img23_png_path = img23_path.replace(".tif", ".png")
#             #     cv2.imwrite(img23_png_path, img)

#             # with rasterio.open(img25_path) as src:
#             #     img = reshape_as_image(src.read())
#             #     img25_png_path = img25_path.replace(".tif", ".png")
#             #     cv2.imwrite(img25_png_path, img)

#             # 2023
#             with rasterio.open(img23_path) as src:
#                 img = src.read()
#                 img = reshape_as_image(img)

#                 # img = img[:, :, :3]

#             # 🔥 NORMALIZE
#                 img = img.astype(np.float32)
#                 img = (img - img.min()) / (img.max() - img.min()) * 255
#                 img = img.astype(np.uint8)

#                 img23_png_path = img23_path.replace(".tif", ".png")
#                 cv2.imwrite(img23_png_path, img)


#         # 2025
#             with rasterio.open(img25_path) as src:
#                 img = src.read()
#                 img = reshape_as_image(img)

#                 # img = img[:, :, :3]

#             # 🔥 NORMALIZE
#                 img = img.astype(np.float32)
#                 img = (img - img.min()) / (img.max() - img.min()) * 255
#                 img = img.astype(np.uint8)

#                 img25_png_path = img25_path.replace(".tif", ".png")
#                 cv2.imwrite(img25_png_path, img)





#             # 🚀 PROCESS
#             png, tif, zip_file = process_change(
#                 img23_path,
#                 img25_path,
#                 output_path
#             )

#             # ✅ SAVE TO DB
#             user = request.user if request.user.is_authenticated else User.objects.first()
#             obj = ChangeResult.objects.create(user=user)

#             obj.uploaded_2023.save(img23.name, File(open(img23_path, 'rb')))
#             obj.uploaded_2025.save(img25.name, File(open(img25_path, 'rb')))

#             obj.result_png.save(os.path.basename(png), File(open(png, 'rb')))
#             obj.result_tif.save(os.path.basename(tif), File(open(tif, 'rb')))
#             obj.result_shp.save(os.path.basename(zip_file), File(open(zip_file, 'rb')))

#             obj.save()

#             # ✅ CONTEXT
#             context = {
#                 'result_png': settings.MEDIA_URL + os.path.relpath(png, settings.MEDIA_ROOT).replace("\\", "/"),
#                 'result_tif': settings.MEDIA_URL + os.path.relpath(tif, settings.MEDIA_ROOT).replace("\\", "/"),
#                 'result_shp': settings.MEDIA_URL + os.path.relpath(zip_file, settings.MEDIA_ROOT).replace("\\", "/"),

#                 'img23': settings.MEDIA_URL + os.path.relpath(img23_png_path, settings.MEDIA_ROOT).replace("\\", "/"),
#                 'img25': settings.MEDIA_URL + os.path.relpath(img25_png_path, settings.MEDIA_ROOT).replace("\\", "/"),
                
#                 'img23_name': os.path.splitext(img23.name)[0],
#                 'img25_name': os.path.splitext(img25.name)[0],
#                 'result_shp_name': 'Change Detection Result',
#             }

#             return render(request, 'result.html', context)

#     else:
#         form = ChangeResultForm()

#     years = list(range(2000, 2027))
#     return render(request, 'upload.html', {'form': form, 'years': years})

# # @subscription_required
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

#         # 🔥 CLEAN OLD DATA
#         for d in [main_dir, change_dir]:
#             if os.path.exists(d):
#                 shutil.rmtree(d)
#             os.makedirs(d)

#         os.makedirs(output_dir, exist_ok=True)

#         # =========================
#         # 🔵 MAIN ZIP HANDLE
#         # =========================
#         if main_zip:
#             main_zip_path = os.path.join(main_dir, main_zip.name)

#             with open(main_zip_path, 'wb+') as f:
#                 for chunk in main_zip.chunks():
#                     f.write(chunk)

#             zipfile.ZipFile(main_zip_path).extractall(main_dir)

#         else:
#             return HttpResponse("❌ Please upload OLD shapefile ZIP")

#         # =========================
#         # 🟢 CHANGE ZIP HANDLE (AUTO)
#         # =========================
#         if not change_zip and prefilled_file:
#             change_zip_path = os.path.join(
#                 settings.BASE_DIR,
#                 prefilled_file.replace('/media/', 'media/')
#             )

#             if not os.path.exists(change_zip_path):
#                 return HttpResponse("❌ Auto shapefile not found")

#         elif change_zip:
#             change_zip_path = os.path.join(change_dir, change_zip.name)

#             with open(change_zip_path, 'wb+') as f:
#                 for chunk in change_zip.chunks():
#                     f.write(chunk)
#         else:
#             return HttpResponse("❌ Change shapefile missing")

#         zipfile.ZipFile(change_zip_path).extractall(change_dir)

#         # =========================
#         # 🔍 FIND SHP FILE
#         # =========================
#         def find_shp(folder):
#             for root, dirs, files in os.walk(folder):
#                 for file in files:
#                     if file.lower().endswith('.shp'):
#                         return os.path.join(root, file)
#             return None

#         main_shp = find_shp(change_dir)
#         change_shp = find_shp(main_dir)

#         print("MAIN SHP:", main_shp)
#         print("CHANGE SHP:", change_shp)

#         # =========================
#         # ❌ ERROR HANDLING
#         # =========================
#         if not main_shp:
#             return HttpResponse("❌ .shp file not found in OLD ZIP")

#         if not change_shp:
#             return HttpResponse("❌ .shp file not found in CHANGE ZIP")

#         # =========================
#         # 🚀 PROCESS RUN
#         # =========================
#         try:
#             result = process_spatial_join(main_shp, change_shp, output_dir)
#         except Exception as e:
#             return HttpResponse(f"❌ Processing Error: {str(e)}")

#         # =========================
#         # ✅ RESULT PAGE
#         # =========================
#         return render(request, 'result1.html', {
#             'result': result
#         })

#     # =========================
#     # 🔹 GET REQUEST
#     # =========================
#     return render(request, 'change.html', {
#         'prefilled_file': prefilled_file,
#         'file_name': file_name
#     })


def upload_images(request):
    if request.method == 'POST':
        form = ChangeResultForm(request.POST, request.FILES)

        year1 = request.POST.get('year1')
        year2 = request.POST.get('year2')

        img23 = request.FILES.get('uploaded_2023')
        img25 = request.FILES.get('uploaded_2025')

        # ✅ Validation
        if not year1 or not year2:
            return HttpResponse("❌ Please select both years")

        if not img23 or not img25:
            return HttpResponse("❌ Please upload both images")

        if form.is_valid():

            # ✅ IMPORTANT: PATH DEFINE KARO
            upload_path = os.path.join(settings.MEDIA_ROOT, 'uploads')
            output_path = os.path.join(settings.MEDIA_ROOT, 'outputs')

            os.makedirs(upload_path, exist_ok=True)
            os.makedirs(output_path, exist_ok=True)

            img23_path = os.path.join(upload_path, img23.name)
            img25_path = os.path.join(upload_path, img25.name)

            # ✅ SAVE FILES
            with open(img23_path, 'wb+') as f:
                for chunk in img23.chunks():
                    f.write(chunk)

            with open(img25_path, 'wb+') as f:
                for chunk in img25.chunks():
                    f.write(chunk)

            

            img23_png_path = build_preview_path(img23_path)
            img25_png_path = build_preview_path(img25_path)
            save_tiff_preview_png(img23_path, img23_png_path)
            save_tiff_preview_png(img25_path, img25_png_path, reference_path=img23_path)





            # 🚀 PROCESS
            png, tif, zip_file = process_change(
                img23_path,
                img25_path,
                output_path
            )

            # ✅ SAVE TO DB
            user = request.user if request.user.is_authenticated else User.objects.first()
            obj = ChangeResult.objects.create(user=user)

            obj.uploaded_2023.save(img23.name, File(open(img23_path, 'rb')))
            obj.uploaded_2025.save(img25.name, File(open(img25_path, 'rb')))

            obj.result_png.save(os.path.basename(png), File(open(png, 'rb')))
            obj.result_tif.save(os.path.basename(tif), File(open(tif, 'rb')))
            obj.result_shp.save(os.path.basename(zip_file), File(open(zip_file, 'rb')))

            obj.save()

            # ✅ CONTEXT
            context = build_result_context(
                png,
                tif,
                zip_file,
                img23_png_path,
                img25_png_path,
                img23.name,
                img25.name,
            )

            return render(request, 'result.html', context)

    else:
        form = ChangeResultForm()

    years = list(range(2000, 2027))
    return render(request, 'upload.html', {'form': form, 'years': years})






import os

def spatial_join_view(request):

    prefilled_file = request.GET.get('file')
    
    file_name = os.path.basename(prefilled_file) if prefilled_file else None

    if request.method == 'POST':

        prefilled_file = request.POST.get('prefilled_file')

        main_zip = request.FILES.get('main_zip')
        change_zip = request.FILES.get('change_zip')

        base_dir = settings.MEDIA_ROOT
        main_dir = os.path.join(base_dir, 'main')
        change_dir = os.path.join(base_dir, 'change')
        output_dir = os.path.join(base_dir, 'spatial_output')

        # 🔥 CLEAN OLD DATA
        for d in [main_dir, change_dir]:
            if os.path.exists(d):
                shutil.rmtree(d)
            os.makedirs(d)

        os.makedirs(output_dir, exist_ok=True)

        # =========================
        # 🔵 MAIN ZIP HANDLE
        # =========================
        if main_zip:
            main_zip_path = os.path.join(main_dir, main_zip.name)

            with open(main_zip_path, 'wb+') as f:
                for chunk in main_zip.chunks():
                    f.write(chunk)

            zipfile.ZipFile(main_zip_path).extractall(main_dir)

        else:
            return HttpResponse("❌ Please upload OLD shapefile ZIP")

        # =========================
        # 🟢 CHANGE ZIP HANDLE (AUTO)
        # =========================
        if not change_zip and prefilled_file:
            change_zip_path = os.path.join(
                settings.BASE_DIR,
                prefilled_file.replace('/media/', 'media/')
            )

            if not os.path.exists(change_zip_path):
                return HttpResponse("❌ Auto shapefile not found")

        elif change_zip:
            change_zip_path = os.path.join(change_dir, change_zip.name)

            with open(change_zip_path, 'wb+') as f:
                for chunk in change_zip.chunks():
                    f.write(chunk)
        else:
            return HttpResponse("❌ Change shapefile missing")

        zipfile.ZipFile(change_zip_path).extractall(change_dir)

        # =========================
        # 🔍 FIND SHP FILE
        # =========================
        def find_shp(folder):
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith('.shp'):
                        return os.path.join(root, file)
            return None

        main_shp = find_shp(change_dir)
        change_shp = find_shp(main_dir)

        print("MAIN SHP:", main_shp)
        print("CHANGE SHP:", change_shp)

        # =========================
        # ❌ ERROR HANDLING
        # =========================
        if not main_shp:
            return HttpResponse("❌ .shp file not found in OLD ZIP")

        if not change_shp:
            return HttpResponse("❌ .shp file not found in CHANGE ZIP")

        # =========================
        # 🚀 PROCESS RUN
        # =========================
        try:
            result = process_spatial_join(main_shp, change_shp, output_dir)
        except Exception as e:
            return HttpResponse(f"❌ Processing Error: {str(e)}")

        # =========================
        # ✅ RESULT PAGE
        # =========================
        return render(request, 'result1.html', {
            'result': result
        })

    # =========================
    # 🔹 GET REQUEST
    # =========================
    return render(request, 'change.html', {
        'prefilled_file': prefilled_file,
        'file_name': file_name
    })







from django.http import FileResponse
import zipfile

def download_excel(request):
    file_path = request.GET.get('file')

    if not os.path.exists(file_path):
        return HttpResponse("File not found")

    return FileResponse(open(file_path, 'rb'), as_attachment=True)

def download_shapefile(request):
    shp_path = request.GET.get('file')

    if not os.path.exists(shp_path):
        return HttpResponse("File not found")

    base = os.path.splitext(shp_path)[0]
    zip_path = base + ".zip"

    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
            f = base + ext
            if os.path.exists(f):
                zipf.write(f, os.path.basename(f))

    return FileResponse(open(zip_path, 'rb'), as_attachment=True)









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
    results = SpatialJoinResult.objects.all().order_by('-created_at')
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




# 🔹 Get Plans
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_plans(request):
    
    plans = SubscriptionPlan.objects.all()
    data = [{"id": p.id, "name": p.name, "price": p.price} for p in plans]
    return JsonResponse(data, safe=False)


# 🔹 Create Payment Order
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_payment(request):
    plan_id = request.data.get("plan_id")
    plan = SubscriptionPlan.objects.get(id=plan_id)

    order = create_order(plan.price)

    return JsonResponse({
        "order_id": order["id"],
        "amount": order["amount"] / 100,
        "plan_id": plan.id
    })


# 🔹 Verify Payment & Activate Subscription
import razorpay # type: ignore
@api_view(['POST'])
@permission_classes([IsAuthenticated])

def verify_payment(request):

    user = request.user

    razorpay_order_id = request.data.get('razorpay_order_id')
    razorpay_payment_id = request.data.get('razorpay_payment_id')
    razorpay_signature = request.data.get('razorpay_signature')
    plan_id = request.data.get("plan_id")

    client = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )

    try:
        client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        })
    except Exception as e:
        return JsonResponse({"error": "Payment verification failed"}, status=400)

    plan = SubscriptionPlan.objects.get(id=plan_id)

    UserSubscription.objects.update_or_create(
        user=user,
        defaults={
            "plan": plan,
            "start_date": timezone.now(),
            "end_date": timezone.now() + timedelta(days=plan.duration_days),
            "is_active": True
        }
    )

    return JsonResponse({"status": "Subscription Activated"})
def payment_page(request):
    return render(request, 'payment.html')

from rest_framework.permissions import IsAdminUser # type: ignore
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_dashboard(request):

    total_users = User.objects.count()

    active_subs = UserSubscription.objects.filter(
        is_active=True,
        end_date__gt=timezone.now()
    ).count()

    expired_subs = UserSubscription.objects.filter(
        end_date__lt=timezone.now()
    ).count()

    return Response({
        "total_users": total_users,
        "active_subscriptions": active_subs,
        "expired_subscriptions": expired_subs
    })
    
@api_view(['GET'])
@permission_classes([IsAdminUser])
def user_list(request):

    data = []

    subs = UserSubscription.objects.select_related('user')

    for sub in subs:
        data.append({
            "username": sub.user.username,
            "email": sub.user.email,
            "plan": sub.plan.name,
            "expiry": sub.end_date,
            "status": "Active" if sub.is_active else "Expired"
        })

    return Response(data)