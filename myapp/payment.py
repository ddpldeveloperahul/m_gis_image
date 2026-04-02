import razorpay # type: ignore
from django.conf import settings

client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_order(amount):
    order = client.order.create({
        "amount": int(amount * 100),  # paise
        "currency": "INR",
        "payment_capture": 1
    })
    return order