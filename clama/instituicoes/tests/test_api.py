"""
Testes da API de instituições — endpoint público e ViewSet admin.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.instituicoes.models import Instituicao
from clama.instituicoes.tests.factories import InstituicaoFactory

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_client(db):
    admin = User.objects.create_user(
        email="admin@clama.test",
        password="test-pass",
        is_clama_admin=True,
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


@pytest.fixture
def non_admin_client(db):
    user = User.objects.create_user(
        email="user@clama.test",
        password="test-pass",
        is_clama_admin=False,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestInstituicaoListPublic:
    """GET /api/instituicoes/ (público, sem paginação)."""

    def test_retorna_200_sem_auth(self, api_client):
        url = reverse("instituicoes-list")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK

    def test_lista_somente_ativas(self, api_client):
        Instituicao.objects.all().delete()
        InstituicaoFactory(ativo=True, ordem=1)
        InstituicaoFactory(ativo=True, ordem=2)
        InstituicaoFactory(ativo=False, ordem=3)

        url = reverse("instituicoes-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

    def test_resposta_e_array_puro_sem_paginacao(self, api_client):
        url = reverse("instituicoes-list")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)

    def test_expoe_apenas_campos_publicos(self, api_client):
        Instituicao.objects.all().delete()
        InstituicaoFactory(ativo=True)

        url = reverse("instituicoes-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert set(response.data[0].keys()) == {"id", "nome", "logo"}

    def test_ordenacao_por_ordem_e_nome(self, api_client):
        Instituicao.objects.all().delete()
        InstituicaoFactory(nome="Beta", ordem=2, ativo=True)
        InstituicaoFactory(nome="Alfa", ordem=1, ativo=True)

        url = reverse("instituicoes-list")
        response = api_client.get(url)

        assert response.data[0]["nome"] == "Alfa"
        assert response.data[1]["nome"] == "Beta"


@pytest.mark.django_db
class TestAdminInstituicaoViewSet:
    """CRUD admin /api/admin/instituicoes/."""

    def test_nao_autenticado_recebe_401(self, api_client):
        url = reverse("admin_api:admin-instituicoes-list")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_nao_admin_recebe_403(self, non_admin_client):
        url = reverse("admin_api:admin-instituicoes-list")
        response = non_admin_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_cria_instituicao(self, admin_client):
        url = reverse("admin_api:admin-instituicoes-list")
        payload = {
            "nome": "Nova Casa",
            "ativo": True,
            "ordem": 5,
        }
        response = admin_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert Instituicao.objects.filter(nome="Nova Casa").exists()

    def test_admin_cria_com_logo_upload(self, admin_client):
        from io import BytesIO

        url = reverse("admin_api:admin-instituicoes-list")
        png = BytesIO(b"\x89PNG\r\n\x1a\n_fake_png_bytes_")
        png.name = "logo.png"
        response = admin_client.post(
            url,
            {"nome": "Com Logo", "ordem": 6, "logo_file": png},
            format="multipart",
        )
        assert response.status_code == status.HTTP_201_CREATED
        inst = Instituicao.objects.get(nome="Com Logo")
        assert inst.logo.startswith("data:image/png;base64,")

    def test_admin_edita_instituicao(self, admin_client):
        instituicao = InstituicaoFactory(nome="Antigo")
        url = reverse(
            "admin_api:admin-instituicoes-detail", kwargs={"id": instituicao.id}
        )
        response = admin_client.patch(url, {"nome": "Novo"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        instituicao.refresh_from_db()
        assert instituicao.nome == "Novo"

    def test_admin_desativa_instituicao(self, admin_client):
        instituicao = InstituicaoFactory(ativo=True)
        url = reverse(
            "admin_api:admin-instituicoes-desativar", kwargs={"id": instituicao.id}
        )
        response = admin_client.post(url)
        assert response.status_code == status.HTTP_200_OK
        instituicao.refresh_from_db()
        assert instituicao.ativo is False

    def test_delete_nao_permitido(self, admin_client):
        instituicao = InstituicaoFactory()
        url = reverse(
            "admin_api:admin-instituicoes-detail", kwargs={"id": instituicao.id}
        )
        response = admin_client.delete(url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
