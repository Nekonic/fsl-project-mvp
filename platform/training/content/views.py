from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from training.content import problems as service
from training.content import serializers
from users import permissions as accounts

CATALOG = ["catalog"]
STAFF = ["staff"]


def stored(problem) -> dict:
    return serializers.StoredDocument(service.document(problem)).data


class Problems(APIView):
    @extend_schema(tags=CATALOG, responses=serializers.LearnerProblemSummary(many=True), operation_id="problems")
    def get(self, request):
        return Response(serializers.LearnerProblemSummary(service.published(), many=True).data)


class LearnerWargames(APIView):
    @extend_schema(tags=CATALOG, responses=serializers.LearnerWargame(many=True), operation_id="wargames")
    def get(self, request):
        return Response(serializers.LearnerWargame(service.wargames(), many=True).data)


class OneProblem(APIView):
    @extend_schema(tags=CATALOG, responses=serializers.LearnerProblem, operation_id="problem")
    def get(self, request, problem_id: int):
        return Response(serializers.LearnerProblem(service.published_problem(problem_id)).data)


class StaffProblems(APIView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.StaffProblem(many=True), operation_id="staff_problems")
    def get(self, request):
        return Response(serializers.StaffProblem(service.problems(), many=True).data)

    @extend_schema(tags=STAFF, request=serializers.Document, responses={201: serializers.StoredDocument},
                   operation_id="staff_problem_create")
    def post(self, request):
        problem = service.save_document(request.data, author=request.user)
        return Response(stored(problem), status=status.HTTP_201_CREATED)


class StaffProblem(APIView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.StoredDocument, operation_id="staff_problem")
    def get(self, request, problem_id: int):
        return Response(stored(service.problem(problem_id)))

    @extend_schema(tags=STAFF, request=serializers.RevisedDocument, responses=serializers.StoredDocument,
                   operation_id="staff_problem_update")
    def put(self, request, problem_id: int):
        given = request.data if isinstance(request.data, dict) else {}
        problem = service.save_document(request.data, given.get("base_revision"), problem_id=problem_id)
        return Response(stored(problem))

    @extend_schema(tags=STAFF, responses={204: None}, operation_id="staff_problem_delete")
    def delete(self, request, problem_id: int):
        service.delete_problem(problem_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class Export(APIView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.Document, operation_id="staff_problem_export")
    def get(self, request, problem_id: int):
        return Response(serializers.Document(service.export(problem_id)).data)


class Import(APIView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF, request=serializers.Document, responses={201: serializers.StoredDocument},
                   operation_id="staff_problem_import")
    def post(self, request):
        problem = service.import_document(request.data, author=request.user)
        return Response(stored(problem), status=status.HTTP_201_CREATED)


class Validate(APIView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF, request=serializers.Document, responses=serializers.Validation,
                   operation_id="staff_problem_validate")
    def post(self, request):
        found = service.validate(request.data)
        return Response(serializers.Validation({"ok": not found, "errors": [error.shown() for error in found]}).data)


class Postures(APIView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.Posture(many=True), operation_id="staff_postures")
    def get(self, request):
        return Response(serializers.Posture(service.postures(), many=True).data)

    @extend_schema(tags=STAFF, request=serializers.Posture, responses={201: serializers.Posture},
                   operation_id="staff_posture_create")
    def post(self, request):
        return Response(serializers.Posture(service.save_posture(request.data)).data, status=status.HTTP_201_CREATED)


class OnePosture(APIView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.Posture, operation_id="staff_posture")
    def get(self, request, posture_id: int):
        return Response(serializers.Posture(service.posture(posture_id)).data)

    @extend_schema(tags=STAFF, request=serializers.Posture, responses=serializers.Posture,
                   operation_id="staff_posture_update")
    def put(self, request, posture_id: int):
        return Response(serializers.Posture(service.save_posture(request.data, posture_id)).data)


class Wargames(APIView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.Wargame(many=True), operation_id="staff_wargames")
    def get(self, request):
        return Response(serializers.Wargame(service.wargames(), many=True,
                                            context={"waf_files": service.waf_files(),
                                                     "objective_names": service.objective_names}).data)
