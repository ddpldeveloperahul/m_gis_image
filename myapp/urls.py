from django.urls import path
from myapp import views
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView # type: ignore

    

urlpatterns = [
    path('home/', views.home, name='home'),
    #api endpoints
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    path('upload/', views.upload_images, name='upload'),
    path('result/', views.result_view, name='change_result'),
    path('run-spatial-join/', views.spatial_join_view, name='result'),
    path('download-excel/', views.download_excel, name='download_excel'),
    path('download-shapefile/', views.download_shapefile, name='download_shapefile'),
    
    # Chunked upload for large files
    path('upload-chunk/', views.upload_chunk, name='upload_chunk'),
    
    path('api/signup/', views.signup_api),
    path('api/login/', views.login_api),
    path('api/logout/', views.logout_api),
    path('api/excel-files/', views.list_excel_files, name='list_excel_files'),
    path('spatial-join/', views.spatial_join_view, name='spatial_join'),
    path('start-processing/', views.start_processing, name='start_processing'),
    path('task-status/<str:task_id>/', views.task_status, name='task_status'),

    
    
    path('', views.login_page),
    path('login/', views.login_page, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_page),

    
      
]

