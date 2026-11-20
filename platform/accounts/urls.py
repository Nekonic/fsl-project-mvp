from django.urls import path

from accounts import views

urlpatterns = [
    path("auth/csrf/", views.Csrf.as_view()),
    path("auth/login/", views.Login.as_view()),
    path("auth/signup/", views.SignUp.as_view()),
    path("auth/logout/", views.Logout.as_view()),
    path("me/", views.Me.as_view()),
    path("staff/users/", views.Users.as_view()),
    path("staff/users/<str:username>/approve/", views.Approve.as_view()),
    path("staff/users/<str:username>/disable/", views.Disable.as_view()),
    path("staff/blocks/", views.Blocks.as_view()),
    path("staff/blocks/<int:block_id>/", views.Unblock.as_view()),
]
