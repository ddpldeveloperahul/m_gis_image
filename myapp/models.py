from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User

class ChangeResult(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    uploaded_2023 = models.FileField(upload_to='uploads/')
    uploaded_2025 = models.FileField(upload_to='uploads/')

    result_png = models.FileField(upload_to='outputs/')
    result_tif = models.FileField(upload_to='outputs/')
    result_shp = models.FileField(upload_to='outputs/')

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Change Result - {self.user.username}"



class SpatialJoinResult(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    main_shapefile = models.FileField(upload_to='uploads/')
    change_shapefile = models.FileField(upload_to='uploads/')

    result_shapefile = models.FileField(upload_to='outputs/')
    result_excel = models.FileField(upload_to='outputs/') # ✅ ADD
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Spatial Join Result - {self.user.username}"