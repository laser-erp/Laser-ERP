from django.urls import path

from . import views

app_name = "production"

urlpatterns = [
    path("stage-register/", views.stage_register, name="stage_register"),
    path("status/", views.production_status, name="status"),
]
