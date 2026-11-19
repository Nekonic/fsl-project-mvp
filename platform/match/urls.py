from django.urls import path, re_path

from match import views

ROUND = "rounds/<int:round_id>/"

urlpatterns = [
    path("leases/", views.Leases.as_view()),
    path("leases/<int:lease_id>/", views.Lease.as_view()),
    path("leases/<int:lease_id>/heartbeat/", views.Heartbeat.as_view()),
    path("leases/<int:lease_id>/close/", views.CloseLease.as_view()),
    path("leases/<int:lease_id>/rounds/", views.LeaseRounds.as_view()),
    path("rounds/", views.Rounds.as_view()),
    path(ROUND, views.RoundDetail.as_view()),
    re_path(r"^rounds/(?P<round_id>[0-9]+)/seats/(?P<side>attack|defence)/join/$", views.Join.as_view()),
    path(f"{ROUND}start/", views.Start.as_view()),
    path(f"{ROUND}end/", views.End.as_view()),
    path(f"{ROUND}score/", views.Score.as_view()),
    path(f"{ROUND}topology/", views.Topology.as_view()),
    path(f"{ROUND}site/requests/", views.SiteRequests.as_view()),
    re_path(r"^rounds/(?P<round_id>[0-9]+)/terminal-auth/(?P<side>attack|defence)/?$", views.TerminalAuth.as_view()),
    path(f"{ROUND}attack/forfeit/", views.AttackForfeit.as_view()),
    path(f"{ROUND}defence/forfeit/", views.DefenceForfeit.as_view()),
    path("staff/range/", views.StaffRange.as_view()),
    path("staff/wargames/<str:wargame_id>/probes/record/", views.RecordProbes.as_view()),
    path("staff/probes/<int:lease_id>/", views.ProbeProgress.as_view()),
]

site = [
    path("site-proxy/<int:round_id>/<str:host>/", views.SiteProxy.as_view()),
    path("site-proxy/<int:round_id>/<str:host>/<path:rest>", views.SiteProxy.as_view()),
]
