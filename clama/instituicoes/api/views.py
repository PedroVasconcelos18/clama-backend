"""
Views públicas da API de instituições.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle

from clama.instituicoes.api.serializers import InstituicaoSerializer
from clama.instituicoes.models import Instituicao


class InstituicaoListView(ListAPIView):
    """
    Lista as instituições parceiras ativas.

    Retorna apenas instituições com `ativo=True`, ordenadas por ordem e nome.
    Não requer autenticação e não é paginado (array puro).
    """

    serializer_class = InstituicaoSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    pagination_class = None

    def get_queryset(self):
        return Instituicao.objects.filter(ativo=True)

    @extend_schema(
        tags=["Instituições"],
        summary="Listar instituições parceiras",
        description="Retorna as instituições ativas, ordenadas por ordem e nome.",
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
