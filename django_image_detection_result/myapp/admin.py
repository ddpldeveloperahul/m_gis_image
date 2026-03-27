from django.contrib import admin
from .models import ChangeResult, SpatialJoinResult

@admin.register(ChangeResult)
class ChangeResultAdmin(admin.ModelAdmin):
    list_display = ('user', 'uploaded_2023', 'uploaded_2025', 'result_png', 'result_tif', 'result_shp', 'created_at')
    readonly_fields = ('created_at',)



@admin.register(SpatialJoinResult)
class SpatialJoinResultAdmin(admin.ModelAdmin):
    list_display = ('user', 'main_shapefile', 'change_shapefile', 'result_shapefile', 'result_excel', 'created_at')
    readonly_fields = ('created_at',)


