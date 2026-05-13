import pytest
from rest_framework.test import APIClient

from clama.blog.models import Comentario, CustomerBanido
from clama.blog.tests.factories import (
    BlogCustomerFactory,
    BlogUserFactory,
    ComentarioFactory,
    CustomerBanidoFactory,
    PostFactory,
)

ADMIN_COMMENTS = "/api/blog/admin/comments/"
ADMIN_BANNED = "/api/blog/admin/banned-customers/"


def _admin_client():
    client = APIClient()
    admin = BlogUserFactory(is_clama_admin=True)
    client.force_authenticate(user=admin)
    return client, admin


def _non_admin_client():
    client = APIClient()
    user = BlogCustomerFactory()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestAdminCommentsList:
    def test_admin_lists_all(self):
        ComentarioFactory()
        ComentarioFactory()
        ComentarioFactory()
        client, _ = _admin_client()
        response = client.get(ADMIN_COMMENTS)
        assert response.status_code == 200
        assert response.json()["count"] == 3

    def test_non_admin_403(self):
        ComentarioFactory()
        client, _ = _non_admin_client()
        response = client.get(ADMIN_COMMENTS)
        assert response.status_code == 403

    def test_filter_by_suspeitos(self):
        # is_suspeito é controlado pelo pre_save signal (Story 5.3) baseado
        # no conteúdo; passar `is_suspeito=True` na factory seria sobrescrito.
        ComentarioFactory(conteudo="Texto pastoral limpo e edificante.")
        suspeito = ComentarioFactory(
            conteudo="Que merda de texto, compre agora curso!"
        )
        client, _ = _admin_client()
        response = client.get(f"{ADMIN_COMMENTS}?status=suspeitos")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["results"][0]["id"] == str(suspeito.id)

    def test_filter_by_post_slug(self):
        post1 = PostFactory(slug="post-um")
        post2 = PostFactory(slug="post-dois")
        ComentarioFactory(post=post1)
        ComentarioFactory(post=post2)
        ComentarioFactory(post=post2)
        client, _ = _admin_client()
        response = client.get(f"{ADMIN_COMMENTS}?post=post-dois")
        body = response.json()
        assert body["count"] == 2


@pytest.mark.django_db
class TestAdminCommentDelete:
    def test_admin_deletes_any(self):
        c = ComentarioFactory()
        client, _ = _admin_client()
        response = client.delete(f"{ADMIN_COMMENTS}{c.id}/")
        assert response.status_code == 204
        assert not Comentario.objects.filter(id=c.id).exists()

    def test_non_admin_cannot_delete(self):
        c = ComentarioFactory()
        client, _ = _non_admin_client()
        response = client.delete(f"{ADMIN_COMMENTS}{c.id}/")
        assert response.status_code == 403


@pytest.mark.django_db
class TestAdminBannedList:
    def test_lists_only_active_bans(self):
        from django.utils import timezone

        active = CustomerBanidoFactory()
        revogado = CustomerBanidoFactory()
        revogado.revogado_em = timezone.now()
        revogado.save()
        client, _ = _admin_client()
        response = client.get(ADMIN_BANNED)
        body = response.json()
        ids = {b["id"] for b in body["results"]}
        assert str(active.id) in ids
        assert str(revogado.id) not in ids

    def test_non_admin_403(self):
        CustomerBanidoFactory()
        client, _ = _non_admin_client()
        response = client.get(ADMIN_BANNED)
        assert response.status_code == 403


@pytest.mark.django_db
class TestAdminBanCreate:
    def test_create_ban(self):
        customer = BlogCustomerFactory()
        client, admin = _admin_client()
        response = client.post(
            ADMIN_BANNED,
            {"customer_id": str(customer.id), "motivo": "comportamento inadequado"},
            format="json",
        )
        assert response.status_code == 201, response.content
        ban = CustomerBanido.objects.get(customer=customer, revogado_em__isnull=True)
        assert ban.motivo == "comportamento inadequado"
        assert ban.banido_por == admin

    def test_idempotent_returns_existing(self):
        customer = BlogCustomerFactory()
        existing = CustomerBanidoFactory(customer=customer)
        client, _ = _admin_client()
        response = client.post(
            ADMIN_BANNED,
            {"customer_id": str(customer.id), "motivo": "outro motivo"},
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(existing.id)
        # Motivo NÃO foi alterado (idempotente)
        existing.refresh_from_db()
        assert existing.motivo != "outro motivo"

    def test_customer_inexistente_returns_404(self):
        client, _ = _admin_client()
        response = client.post(
            ADMIN_BANNED,
            {
                "customer_id": 99999999,
                "motivo": "test motivo valido",
            },
            format="json",
        )
        assert response.status_code == 404

    def test_motivo_curto_returns_400(self):
        customer = BlogCustomerFactory()
        client, _ = _admin_client()
        response = client.post(
            ADMIN_BANNED,
            {"customer_id": str(customer.id), "motivo": "x"},
            format="json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestAdminBanRevoke:
    def test_revoke_by_customer_id(self):
        customer = BlogCustomerFactory()
        ban = CustomerBanidoFactory(customer=customer)
        client, admin = _admin_client()
        response = client.delete(f"{ADMIN_BANNED}{customer.id}/")
        assert response.status_code == 204
        ban.refresh_from_db()
        assert ban.revogado_em is not None
        assert ban.revogado_por == admin

    def test_revoke_when_no_active_ban_returns_404(self):
        customer = BlogCustomerFactory()
        client, _ = _admin_client()
        response = client.delete(f"{ADMIN_BANNED}{customer.id}/")
        assert response.status_code == 404

    def test_double_revoke_second_returns_404(self):
        customer = BlogCustomerFactory()
        CustomerBanidoFactory(customer=customer)
        client, _ = _admin_client()
        r1 = client.delete(f"{ADMIN_BANNED}{customer.id}/")
        assert r1.status_code == 204
        r2 = client.delete(f"{ADMIN_BANNED}{customer.id}/")
        assert r2.status_code == 404
