from django.urls import path

from blueteam import views

urlpatterns = [
    path("", views.score),
    path("detections/", views.detections),
    path("rules/", views.rules),
]
