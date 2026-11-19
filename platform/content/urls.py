from django.urls import path

from content import views

urlpatterns = [
    path("problems/", views.Problems.as_view()),
    path("problems/<int:problem_id>/", views.OneProblem.as_view()),
    path("staff/problems/", views.StaffProblems.as_view()),
    path("staff/problems/validate/", views.Validate.as_view()),
    path("staff/problems/import/", views.Import.as_view()),
    path("staff/problems/<int:problem_id>/", views.StaffProblem.as_view()),
    path("staff/problems/<int:problem_id>/export/", views.Export.as_view()),
    path("staff/postures/", views.Postures.as_view()),
    path("staff/postures/<int:posture_id>/", views.OnePosture.as_view()),
    path("staff/wargames/", views.Wargames.as_view()),
]
