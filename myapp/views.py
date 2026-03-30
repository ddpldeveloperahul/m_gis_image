from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.conf import settings
from requests import request
from .forms import ChangeResultForm, SpatialJoinForm
from .utils import process_change,process_spatial_join
import os
import zipfile
import shutil
import cv2 
from .models import SpatialJoinResult,ChangeResult
from django.contrib.auth.models import User
from django.core.files import File
from django.views.decorators.csrf import csrf_exempt
from PIL import Image


def home(request):
    return render(request, 'base.html')
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

            # 🔥 TIF → PNG
            import rasterio
            from rasterio.plot import reshape_as_image
            import cv2
            import numpy as np

            # with rasterio.open(img23_path) as src:
            #     img = reshape_as_image(src.read())
            #     img23_png_path = img23_path.replace(".tif", ".png")
            #     cv2.imwrite(img23_png_path, img)

            # with rasterio.open(img25_path) as src:
            #     img = reshape_as_image(src.read())
            #     img25_png_path = img25_path.replace(".tif", ".png")
            #     cv2.imwrite(img25_png_path, img)

            # 2023
            with rasterio.open(img23_path) as src:
                img = src.read()
                img = reshape_as_image(img)

                # img = img[:, :, :3]

            # 🔥 NORMALIZE
                img = img.astype(np.float32)
                img = (img - img.min()) / (img.max() - img.min()) * 255
                img = img.astype(np.uint8)

                img23_png_path = img23_path.replace(".tif", ".png")
                cv2.imwrite(img23_png_path, img)


        # 2025
            with rasterio.open(img25_path) as src:
                img = src.read()
                img = reshape_as_image(img)

                # img = img[:, :, :3]

            # 🔥 NORMALIZE
                img = img.astype(np.float32)
                img = (img - img.min()) / (img.max() - img.min()) * 255
                img = img.astype(np.uint8)

                img25_png_path = img25_path.replace(".tif", ".png")
                cv2.imwrite(img25_png_path, img)





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
            context = {
                'result_png': settings.MEDIA_URL + os.path.relpath(png, settings.MEDIA_ROOT).replace("\\", "/"),
                'result_tif': settings.MEDIA_URL + os.path.relpath(tif, settings.MEDIA_ROOT).replace("\\", "/"),
                'result_shp': settings.MEDIA_URL + os.path.relpath(zip_file, settings.MEDIA_ROOT).replace("\\", "/"),

                'img23': settings.MEDIA_URL + os.path.relpath(img23_png_path, settings.MEDIA_ROOT).replace("\\", "/"),
                'img25': settings.MEDIA_URL + os.path.relpath(img25_png_path, settings.MEDIA_ROOT).replace("\\", "/"),
            }

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






from django.contrib.auth import authenticate, login, logout
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from myapp.serializers import SignupSerializer, LoginSerializer, SpatialJoinResultSerializer


# ✅ SIGNUP


@api_view(['POST'])
@csrf_exempt
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


# ✅ LOGIN

@api_view(['POST'])
@csrf_exempt
def login_api(request):
    data = request.data.copy()
    if 'usename' in data and not data.get('username'):
        data['username'] = data['usename']

    serializer = LoginSerializer(data=data)

    if serializer.is_valid():
        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        user = authenticate(username=username, password=password)

        if user is None:
            return Response({"error": "Invalid credentials"}, status=401)

        login(request, user)

        return Response({
            "message": "Login successful",
            "user_id": user.id
        })

    return Response(serializer.errors, status=400)


# ✅ LOGOUT
# @api_view(['POST'])
# def logout_api(request):
#     logout(request)
#     return Response({"message": "Logged out successfully"})

from django.shortcuts import redirect

@api_view(['POST'])
def logout_api(request):
    logout(request)
    return redirect('/login/')   # 🔥 redirect after logout

@csrf_exempt
@api_view(['GET'])
def list_excel_files(request):
    results = SpatialJoinResult.objects.all().order_by('-created_at')
    serializer = SpatialJoinResultSerializer(results, many=True, context={'request': request})
    return Response(serializer.data)








def login_page(request):
    return render(request, 'login.html')

def signup_page(request):
    return render(request, 'signup.html')








