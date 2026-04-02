from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

class ChangeResult(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    uploaded_2023 = models.FileField(upload_to='uploads/')
    uploaded_2025 = models.FileField(upload_to='uploads/')

    result_png = models.FileField(upload_to='images_upload/')
    result_tif = models.FileField(upload_to='images_upload/')
    result_shp = models.FileField(upload_to='images_upload/')

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Change Result - {self.user.username}"



class SpatialJoinResult(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    main_shapefile = models.FileField(upload_to='shapefiles/')
    change_shapefile = models.FileField(upload_to='shapefiles/')

    result_shapefile = models.FileField(upload_to='output/')
    result_excel = models.FileField(upload_to='output/') # ✅ ADD
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Spatial Join Result - {self.user.username}"
    
    
# 🔹 Subscription Plans
class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=100)
    price = models.FloatField()
    duration_days = models.IntegerField(default=365)
    # max_requests = models.IntegerField(default=1000)

    def __str__(self):
        return self.name


# 🔹 User Subscription
class UserSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.end_date:
            self.end_date = self.start_date + timedelta(days=self.plan.duration_days)
        super().save(*args, **kwargs)

    def is_valid(self):
        return self.is_active and self.end_date > timezone.now()


# 🔹 API Usage Tracking
# class APIUsage(models.Model):
#     user = models.OneToOneField(User, on_delete=models.CASCADE)
#     request_count = models.IntegerField(default=0)
#     reset_date = models.DateTimeField(default=timezone.now)