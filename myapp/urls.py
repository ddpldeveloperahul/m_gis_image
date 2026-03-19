from django.urls import path
from .views import download_shapefile, logout_api, signup_api, login_api, logout_api,spatial_join_view, upload_images, download_excel
from myapp import views

urlpatterns = [
    path('home/', views.home, name='home'),
    #api endpoints
    path('', upload_images, name='upload'),
    path('run-spatial-join/', spatial_join_view, name='result'),
    path('download-excel/', download_excel, name='download_excel'),
    path('download-shapefile/', download_shapefile, name='download_shapefile'),
    
    
    
    path('api/signup/', signup_api),
    path('api/login/', login_api),
    path('api/logout/', logout_api),
    
    
    path('login/', views.login_page),
    path('signup/', views.signup_page),
    path('api/excel-files/', views.list_excel_files, name='list_excel_files'),
]
