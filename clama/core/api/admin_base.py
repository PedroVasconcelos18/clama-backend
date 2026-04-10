"""
Classes base para views de admin do Clama.

IMPORTANTE: Toda view admin nova deve herdar de AdminAPIView ou AdminGenericAPIView.
Isso garante que a autenticação JWT e a permissão IsClamaAdmin sejam aplicadas
automaticamente.

Uso:
    from clama.core.api.admin_base import AdminAPIView, AdminGenericAPIView

    class MyAdminView(AdminAPIView):
        def get(self, request):
            ...

    class MyAdminListView(AdminGenericAPIView, ListAPIView):
        ...
"""

from rest_framework.generics import GenericAPIView
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from clama.core.pastoral_messages import MSG_NOT_AUTHENTICATED, MSG_NO_PERMISSION
from clama_backend.users.permissions import IsClamaAdmin


class AdminAPIView(APIView):
    """
    View base para endpoints admin que usa APIView.

    Aplica automaticamente:
    - Autenticação JWT
    - Permissão IsClamaAdmin

    401 quando não autenticado, 403 quando não é admin.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsClamaAdmin]

    def permission_denied(self, request, message=None, code=None):
        """
        Sobrescreve para retornar mensagens pastorais.
        """
        from rest_framework.exceptions import NotAuthenticated, PermissionDenied

        if not request.user or not request.user.is_authenticated:
            raise NotAuthenticated(detail=MSG_NOT_AUTHENTICATED)
        raise PermissionDenied(detail=MSG_NO_PERMISSION)


class AdminGenericAPIView(GenericAPIView):
    """
    View base para endpoints admin que usa GenericAPIView.

    Aplica automaticamente:
    - Autenticação JWT
    - Permissão IsClamaAdmin

    401 quando não autenticado, 403 quando não é admin.

    Útil quando você precisa de funcionalidades como serializers, querysets, etc.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsClamaAdmin]

    def permission_denied(self, request, message=None, code=None):
        """
        Sobrescreve para retornar mensagens pastorais.
        """
        from rest_framework.exceptions import NotAuthenticated, PermissionDenied

        if not request.user or not request.user.is_authenticated:
            raise NotAuthenticated(detail=MSG_NOT_AUTHENTICATED)
        raise PermissionDenied(detail=MSG_NO_PERMISSION)
