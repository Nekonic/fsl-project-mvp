from django.urls import path

from lessons import views

LESSON = "lessons/<int:round_id>/"

urlpatterns = [
    path("lessons/", views.Lessons.as_view()),
    path(LESSON, views.OneLesson.as_view()),
    path(f"{LESSON}steps/<int:order>/check/", views.CheckStep.as_view()),
    path(f"{LESSON}steps/<int:order>/hint/", views.StepHint.as_view()),
    path(f"{LESSON}end/", views.EndLesson.as_view()),
    path("staff/steps/<int:problem_id>/<int:order>/try/", views.TryStep.as_view()),
]
