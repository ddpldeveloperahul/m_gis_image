from django.http import JsonResponse
from django.utils import timezone
from functools import wraps
from .models import UserSubscription

def subscription_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):

        # 🔐 check login
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Login required"}, status=401)

        user = request.user

        # 🔎 get active subscription safely
        sub = UserSubscription.objects.filter(
            user=user,
            is_active=True
        ).first()

        if not sub:
            return JsonResponse({"error": "No active subscription"}, status=403)

        # ⏰ expiry check
        if sub.end_date < timezone.now():
            sub.is_active = False
            sub.save()
            return JsonResponse({"error": "Subscription expired"}, status=403)

        return view_func(request, *args, **kwargs)

    return wrapper