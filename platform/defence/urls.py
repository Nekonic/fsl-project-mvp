from django.urls import path

from defence import views, views_kibana

ROUND = "rounds/<int:round_id>/defence/"

urlpatterns = [
    path(f"{ROUND}state/", views.State.as_view()),
    path(f"{ROUND}alerts/", views.Alerts.as_view()),
    path(f"{ROUND}traffic/", views.Traffic.as_view()),
    path(f"{ROUND}probes/", views.Probes.as_view()),
    path(f"{ROUND}ids/rules/", views.IdsRules.as_view()),
    path(f"{ROUND}ids/rules/versions/", views.IdsVersions.as_view()),
    path(f"{ROUND}ids/rules/check/", views.IdsCheck.as_view()),
    path(f"{ROUND}ids/rules/test/", views.IdsTest.as_view()),
    path(f"{ROUND}ids/rules/tests/<int:test_id>/", views.IdsTestResult.as_view()),
    path(f"{ROUND}ids/rules/apply/", views.IdsApply.as_view()),
    path(f"{ROUND}ids/disabled/", views.IdsDisabled.as_view()),
    path(f"{ROUND}ids/disabled/<int:sid>/", views.IdsEnable.as_view()),
    path(f"{ROUND}waf/", views.Waf.as_view()),
    path(f"{ROUND}waf/versions/", views.WafVersions.as_view()),
    path(f"{ROUND}waf/check/", views.WafCheck.as_view()),
    path(f"{ROUND}waf/test/", views.WafTest.as_view()),
    path(f"{ROUND}waf/tests/<int:test_id>/", views.WafTestResult.as_view()),
    path(f"{ROUND}waf/apply/", views.WafApply.as_view()),
    path(f"{ROUND}terminal/", views.Terminal.as_view()),
    path(f"{ROUND}kibana/", views.Kibana.as_view()),
]

gate = [
    path("kibana-gate/", views_kibana.KibanaGate.as_view()),
]
