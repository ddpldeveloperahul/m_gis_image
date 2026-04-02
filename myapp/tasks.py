from django.utils import timezone
from django.core.mail import send_mail
from .models import UserSubscription


def send_expiry_emails():
    today = timezone.now().date()

    subs = UserSubscription.objects.filter(is_active=True)

    for sub in subs:
        days_left = (sub.end_date.date() - today).days

        user_email = sub.user.email

        # 🔔 7 days before
        if days_left == 7:
            send_mail(
                "Subscription Expiring Soon",
                "Your subscription will expire in 7 days.",
                "noreply@yourapp.com",
                [user_email]
            )

        # 🔔 1 day before
        elif days_left == 1:
            send_mail(
                "Subscription Expiring Tomorrow",
                "Your subscription will expire tomorrow.",
                "noreply@yourapp.com",
                [user_email]
            )

        # ❌ Expired
        elif days_left < 0 and sub.is_active:
            sub.is_active = False
            sub.save()

            send_mail(
                "Subscription Expired",
                "Your subscription has expired. Please renew.",
                "noreply@yourapp.com",
                [user_email]
            )