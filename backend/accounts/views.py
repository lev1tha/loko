from django.contrib.auth import get_user_model
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer

from .permissions import IsAdmin
from .serializers import (
    LokoTokenObtainPairSerializer,
    UserCreateSerializer,
    UserSerializer,
)

User = get_user_model()


@extend_schema_view(
    post=extend_schema(
        request=inline_serializer(
            "LokoTokenObtainPairRequest",
            {"username": serializers.CharField(), "password": serializers.CharField()},
        ),
        responses=inline_serializer(
            "LokoTokenObtainPairResponse",
            {
                "access": serializers.CharField(),
                "refresh": serializers.CharField(),
                "user": UserSerializer(),
            },
        ),
    )
)
class LokoTokenObtainPairView(TokenObtainPairView):
    """Public login endpoint — issues access/refresh tokens + user payload."""

    serializer_class = LokoTokenObtainPairSerializer


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("id")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return UserCreateSerializer
        return UserSerializer

    def get_permissions(self):
        # Only admins manage users; everyone may read their own profile via /me.
        if self.action == "me":
            return [IsAuthenticated()]
        return [IsAdmin()]

    @extend_schema(responses=UserSerializer)
    @action(detail=False, methods=["get"])
    def me(self, request):
        return Response(UserSerializer(request.user).data)
