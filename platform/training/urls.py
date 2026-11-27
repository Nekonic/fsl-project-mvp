from django.urls import path, re_path

from training.attack import views as attack
from training.content import views as content
from training.defence import views as defence
from training.defence import views_kibana
from training.round import views as rounds

ROUND = "rounds/<int:round_id>/"
ATTACK = "rounds/<int:round_id>/attack/"
DEFENCE = "rounds/<int:round_id>/defence/"

content_urls = [
    path("problems/", content.Problems.as_view()),
    path("problems/<int:problem_id>/", content.OneProblem.as_view()),
    path("staff/problems/", content.StaffProblems.as_view()),
    path("staff/problems/validate/", content.Validate.as_view()),
    path("staff/problems/import/", content.Import.as_view()),
    path("staff/problems/<int:problem_id>/", content.StaffProblem.as_view()),
    path("staff/problems/<int:problem_id>/export/", content.Export.as_view()),
    path("staff/postures/", content.Postures.as_view()),
    path("staff/postures/<int:posture_id>/", content.OnePosture.as_view()),
    path("staff/wargames/", content.Wargames.as_view()),
]

defence_urls = [
    path(f"{DEFENCE}state/", defence.State.as_view()),
    path(f"{DEFENCE}probes/", defence.Probes.as_view()),
    path(f"{DEFENCE}ids/rules/", defence.IdsRules.as_view()),
    path(f"{DEFENCE}ids/rules/versions/", defence.IdsVersions.as_view()),
    path(f"{DEFENCE}ids/rules/versions/<int:version>/", defence.IdsVersion.as_view()),
    path(f"{DEFENCE}ids/rules/test/", defence.IdsTest.as_view()),
    path(f"{DEFENCE}ids/rules/tests/<int:test_id>/", defence.IdsTestResult.as_view()),
    path(f"{DEFENCE}waf/", defence.Waf.as_view()),
    path(f"{DEFENCE}waf/versions/", defence.WafVersions.as_view()),
    path(f"{DEFENCE}waf/versions/<int:version>/", defence.WafVersion.as_view()),
    path(f"{DEFENCE}waf/check/", defence.WafCheck.as_view()),
    path(f"{DEFENCE}waf/test/", defence.WafTest.as_view()),
    path(f"{DEFENCE}waf/tests/<int:test_id>/", defence.WafTestResult.as_view()),
    path(f"{DEFENCE}waf/apply/", defence.WafApply.as_view()),
    path(f"{DEFENCE}terminal/", defence.Terminal.as_view()),
    path(f"{DEFENCE}ids/terminal/", defence.IdsTerminal.as_view()),
    path(f"{DEFENCE}kibana/", defence.Kibana.as_view()),
]

attack_urls = [
    path(f"{ATTACK}state/", attack.State.as_view()),
    path(f"{ATTACK}cases/", attack.Cases.as_view()),
    path(f"{ATTACK}requests/", attack.Requests.as_view()),
    path(f"{ATTACK}tools/", attack.Tools.as_view()),
    path(f"{ATTACK}tools/<int:run_id>/", attack.ToolRun.as_view()),
    path(f"{ATTACK}loot/", attack.Loot.as_view()),
    path(f"{ATTACK}origins/next/", attack.NextOrigin.as_view()),
    path(f"{ATTACK}terminal/", attack.Terminal.as_view()),
]

round_urls = [
    path("allocations/", rounds.Allocations.as_view()),
    path("allocations/<int:allocation_id>/", rounds.Allocation.as_view()),
    path("allocations/<int:allocation_id>/heartbeat/", rounds.Heartbeat.as_view()),
    path("allocations/<int:allocation_id>/close/", rounds.CloseAllocation.as_view()),
    path("allocations/<int:allocation_id>/rounds/", rounds.AllocationRounds.as_view()),
    path("rounds/", rounds.Rounds.as_view()),
    path(ROUND, rounds.RoundDetail.as_view()),
    re_path(r"^rounds/(?P<round_id>[0-9]+)/players/(?P<side>attack|defence)/join/$", rounds.Join.as_view()),
    path(f"{ROUND}start/", rounds.Start.as_view()),
    path(f"{ROUND}end/", rounds.End.as_view()),
    path(f"{ROUND}score/", rounds.Score.as_view()),
    path(f"{ROUND}topology/", rounds.Topology.as_view()),
    path(f"{ROUND}site/requests/", rounds.SiteRequests.as_view()),
    re_path(r"^rounds/(?P<round_id>[0-9]+)/terminal-auth/attack/?$", rounds.AttackTerminalAuth.as_view()),
    re_path(r"^rounds/(?P<round_id>[0-9]+)/terminal-auth/defence/?$", rounds.DefenceTerminalAuth.as_view()),
    re_path(r"^rounds/(?P<round_id>[0-9]+)/terminal-auth/ids/?$", rounds.IdsTerminalAuth.as_view()),
    path(f"{ROUND}debrief/", rounds.Debrief.as_view()),
    path("bot-steps/", rounds.BotSteps.as_view()),
    path("records/", rounds.Records.as_view()),
    path("records/<int:record_id>/", rounds.Record.as_view()),
    path("bot-runs/claim/", rounds.BotRunClaim.as_view()),
    path("bot-runs/<int:run_id>/notes/", rounds.BotRunNotes.as_view()),
    path("bot-runs/<int:run_id>/finish/", rounds.BotRunFinish.as_view()),
    path(f"{ROUND}attack/forfeit/", rounds.AttackForfeit.as_view()),
    path(f"{ROUND}defence/forfeit/", rounds.DefenceForfeit.as_view()),
    path("staff/range/", rounds.StaffRange.as_view()),
    path("staff/range/fabric/", rounds.StaffFabric.as_view()),
    path("staff/range/leftovers/", rounds.StaffLeftovers.as_view()),
    path("staff/range/pool/", rounds.StaffPool.as_view()),
    path("staff/wargames/<str:wargame_id>/probes/record/", rounds.RecordProbes.as_view()),
    path("staff/probes/<int:allocation_id>/", rounds.ProbeProgress.as_view()),
]

gate = [
    path("kibana-gate/", views_kibana.KibanaGate.as_view()),
]

site = [
    path("site-proxy/<int:round_id>/<str:host>/", rounds.SiteProxy.as_view()),
    path("site-proxy/<int:round_id>/<str:host>/<path:rest>", rounds.SiteProxy.as_view()),
]
