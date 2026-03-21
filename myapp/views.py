from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.conf import settings
from requests import request
from .forms import ChangeResultForm, SpatialJoinForm
from .utils import process_change,process_spatial_join
import os
import zipfile
import shutil
from .models import SpatialJoinResult,ChangeResult
from django.contrib.auth.models import User
from django.core.files import File
from django.views.decorators.csrf import csrf_exempt


def home(request):
    return render(request, 'base.html')
def upload_images(request):
    if request.method == 'POST':
        form = ChangeResultForm(request.POST, request.FILES)
        if form.is_valid():
            # img23 = request.FILES['image_2023']
            # img25 = request.FILES['image_2025']
            img23 = request.FILES['uploaded_2023']
            img25 = request.FILES['uploaded_2025']

            upload_path = os.path.join(settings.MEDIA_ROOT, 'uploads')
            output_path = os.path.join(settings.MEDIA_ROOT, 'outputs')

            os.makedirs(upload_path, exist_ok=True)
            os.makedirs(output_path, exist_ok=True)

            img23_path = os.path.join(upload_path, img23.name)
            img25_path = os.path.join(upload_path, img25.name)

            # Save uploaded files
            with open(img23_path, 'wb+') as f:
                for chunk in img23.chunks():
                    f.write(chunk)

            with open(img25_path, 'wb+') as f:
                for chunk in img25.chunks():
                    f.write(chunk)

            # 🔥 PROCESS
            png, tif, zip_file = process_change(
                img23_path,
                img25_path,
                output_path
            )

            # =====================================================
            # 🔥 SAVE TO DATABASE (THIS WAS MISSING)
            # =====================================================

            user = request.user if request.user.is_authenticated else User.objects.first()

            obj = ChangeResult.objects.create(user=user)

            obj.uploaded_2023.save(img23.name, File(open(img23_path, 'rb')))
            obj.uploaded_2025.save(img25.name, File(open(img25_path, 'rb')))

            obj.result_png.save(os.path.basename(png), File(open(png, 'rb')))
            obj.result_tif.save(os.path.basename(tif), File(open(tif, 'rb')))
            obj.result_shp.save(os.path.basename(zip_file), File(open(zip_file, 'rb')))

            obj.save()

            print("✅ CHANGE RESULT SAVED")

            # =====================================================

            # Convert to MEDIA URL
            relative_png = os.path.relpath(png, settings.MEDIA_ROOT)
            relative_tif = os.path.relpath(tif, settings.MEDIA_ROOT)
            relative_zip = os.path.relpath(zip_file, settings.MEDIA_ROOT)

            context = {
                'result_png': settings.MEDIA_URL + relative_png.replace("\\", "/"),
                'result_tif': settings.MEDIA_URL + relative_tif.replace("\\", "/"),
                'result_shp': settings.MEDIA_URL + relative_zip.replace("\\", "/"),
            }

            return render(request, 'result.html', context)

    else:
        form = ChangeResultForm()

    return render(request, 'upload.html', {'form': form})

def spatial_join_view(request):
    if request.method == 'POST':
        main_zip = request.FILES.get('main_zip')
        change_zip = request.FILES.get('change_zip')

        if not main_zip or not change_zip:
            return HttpResponse("❌ Please upload both ZIP files")

        try:
            import shutil

            base_dir = settings.MEDIA_ROOT
            main_dir = os.path.join(base_dir, 'main')
            change_dir = os.path.join(base_dir, 'change')
            output_dir = os.path.join(base_dir, 'output')

            # Clean folders
            for d in [main_dir, change_dir]:
                if os.path.exists(d):
                    shutil.rmtree(d)
                os.makedirs(d)

            os.makedirs(output_dir, exist_ok=True)

            # Save ZIP files
            main_zip_path = os.path.join(main_dir, main_zip.name)
            change_zip_path = os.path.join(change_dir, change_zip.name)

            with open(main_zip_path, 'wb+') as f:
                for chunk in main_zip.chunks():
                    f.write(chunk)

            with open(change_zip_path, 'wb+') as f:
                for chunk in change_zip.chunks():
                    f.write(chunk)

            # Extract ZIP
            zipfile.ZipFile(main_zip_path).extractall(main_dir)
            zipfile.ZipFile(change_zip_path).extractall(change_dir)

            # Find SHP
            def find_shp(folder):
                for root, dirs, files in os.walk(folder):
                    for file in files:
                        if file.endswith('.shp'):
                            return os.path.join(root, file)
                return None

            main_shp = find_shp(main_dir)
            change_shp = find_shp(change_dir)

            # 🔥 RUN PROCESS
            result = process_spatial_join(main_shp, change_shp, output_dir)

            # =====================================================
            # 🔥 SAVE TO DATABASE (THIS WAS MISSING)
            # =====================================================

            with open(result['shapefile'], 'rb') as shp_file, open(result['excel'], 'rb') as excel_file:

                SpatialJoinResult.objects.create(
                    user=request.user if request.user.is_authenticated else User.objects.first(),

                    main_shapefile=File(open(main_zip_path, 'rb'), name=os.path.basename(main_zip_path)),
                    change_shapefile=File(open(change_zip_path, 'rb'), name=os.path.basename(change_zip_path)),

                    result_shapefile=File(shp_file, name=os.path.basename(result['shapefile'])),
                    result_excel=File(excel_file, name=os.path.basename(result['excel']))
                )

            # =====================================================

            return render(request, 'result1.html', {'result': result})

        except Exception as e:
            return HttpResponse(f"❌ Error: {str(e)}")

    return render(request, 'change.html')
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

@csrf_exempt
@api_view(['POST'])
def signup_api(request):
    data = request.data.copy()

    # Normalize keys for typos and alternate spelling
    if 'name' in data and not data.get('username'):
        data['username'] = data['name']
    if 'usenama' in data and not data.get('username'):
        data['username'] = data['usenama']

    if 'passwod' in data and not data.get('password'):
        data['password'] = data['passwod']

    # confirm password can be sent as confirm_password or confirm-passowd
    if 'confirm-passowd' in data and not data.get('confirm_password'):
        data['confirm_password'] = data['confirm-passowd']
    if 'confirm_passowd' in data and not data.get('confirm_password'):
        data['confirm_password'] = data['confirm_passowd']

    serializer = SignupSerializer(data=data)

    if serializer.is_valid():
        user = serializer.save()
        return Response({
            "message": "User created successfully",
            "user_id": user.id
        })

    return Response(serializer.errors, status=400)


@csrf_exempt
@api_view(['GET'])
def list_excel_files(request):
    results = SpatialJoinResult.objects.all().order_by('-created_at')
    serializer = SpatialJoinResultSerializer(results, many=True, context={'request': request})
    return Response(serializer.data)




# @api_view(['GET'])
# def list_excel_files(request):
#     if not request.user.is_authenticated:
#         return Response({"error": "Login required"}, status=401)

#     results = SpatialJoinResult.objects.filter(user=request.user).order_by('-created_at')

#     serializer = SpatialJoinResultSerializer(results, many=True, context={'request': request})
#     return Response(serializer.data)



# ✅ LOGIN
@api_view(['POST'])
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
@api_view(['POST'])
def logout_api(request):
    logout(request)
    return Response({"message": "Logged out successfully"})



def login_page(request):
    return render(request, 'login.html')

def signup_page(request):
    return render(request, 'signup.html')

# from django.contrib.auth.models import User
# from django.contrib.auth import authenticate, login, logout
# from rest_framework.decorators import api_view
# from rest_framework.response import Response
# from rest_framework import status


# # ✅ SIGNUP API
# @api_view(['POST'])
# def signup_api(request):
#     username = request.data.get('username')
#     email = request.data.get('email')
#     password = request.data.get('password')

#     if not username or not password:
#         return Response({"error": "Username and password required"}, status=400)

#     if User.objects.filter(username=username).exists():
#         return Response({"error": "Username already exists"}, status=400)

#     user = User.objects.create_user(
#         username=username,
#         email=email,
#         password=password
#     )

#     return Response({
#         "message": "User created successfully",
#         "user_id": user.id
#     })


# # ✅ LOGIN API
# @api_view(['POST'])
# def login_api(request):
#     username = request.data.get('username')
#     password = request.data.get('password')
#     user = authenticate(username=username, password=password)
#     if user is None:
#         return Response({"error": "Invalid credentials"}, status=401)

#     login(request, user)

#     return Response({
#         "message": "Login successful",
#         "user_id": user.id
#     })


# # ✅ LOGOUT API
# @api_view(['POST'])
# def logout_api(request):
#     logout(request)
#     return Response({"message": "Logged out successfully"})