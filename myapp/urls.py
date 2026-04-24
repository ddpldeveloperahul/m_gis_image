from django.urls import path
from .views import  download_shapefile ,logout_api, signup_api, login_api, spatial_join_view, download_excel, logout_view
from myapp import views
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView # type: ignore
    

urlpatterns = [
    path('home/', views.home, name='home'),
    #api endpoints
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    path('upload/', views.upload_images, name='upload'),
    path('run-spatial-join/', spatial_join_view, name='result'),
    path('download-excel/', download_excel, name='download_excel'),
    path('download-shapefile/', download_shapefile, name='download_shapefile'),
    
    
    
    path('api/signup/', signup_api),
    path('api/login/', login_api),
    path('api/logout/', logout_api),
    path('api/excel-files/', views.list_excel_files, name='list_excel_files'),
    path('spatial-join/', views.spatial_join_view, name='spatial_join'),

    
    
    path('', views.login_page),
    path('login/', views.login_page, name='login'),
    path('logout/', logout_view, name='logout'),
    path('signup/', views.signup_page),

    
      
]


