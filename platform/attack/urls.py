from django.urls import path

from attack import views

BASE = "rounds/<int:round_id>/attack/"

urlpatterns = [
    path(f"{BASE}state/", views.State.as_view()),
    path(f"{BASE}cases/", views.Cases.as_view()),
    path(f"{BASE}requests/", views.Requests.as_view()),
    path(f"{BASE}tools/", views.Tools.as_view()),
    path(f"{BASE}tools/<int:run_id>/", views.ToolRun.as_view()),
    path(f"{BASE}loot/", views.Loot.as_view()),
    path(f"{BASE}origins/next/", views.NextOrigin.as_view()),
    path(f"{BASE}terminal/", views.Terminal.as_view()),
]
