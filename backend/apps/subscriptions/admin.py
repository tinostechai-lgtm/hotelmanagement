from django.contrib import admin

from .models import Plan, SaasPayment, Subscription

admin.site.register(Plan)
admin.site.register(Subscription)
admin.site.register(SaasPayment)
