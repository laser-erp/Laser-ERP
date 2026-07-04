from django.urls import path

from . import views

app_name = "procurement"

urlpatterns = [
    path("priemka/sozdat/", views.goods_receipt_create, name="goods_receipt_create"),
]
