from django.urls import path

from events import views

urlpatterns = [
    path("rounds/<int:round_id>/events/", views.RoundEvents.as_view()),
]
