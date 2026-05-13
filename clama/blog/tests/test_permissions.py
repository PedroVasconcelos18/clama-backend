from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from clama.blog.permissions import IsCommentOwner, IsUnbannedCustomer
from clama.blog.tests.factories import (
    BlogCustomerFactory,
    BlogUserFactory,
    ComentarioFactory,
    CustomerBanidoFactory,
)


def _request_with_user(user):
    request = MagicMock()
    request.user = user
    return request


class TestIsUnbannedCustomerUnit:
    def test_anonymous_user_denied(self):
        request = _request_with_user(AnonymousUser())
        assert IsUnbannedCustomer().has_permission(request, view=None) is False

    @pytest.mark.django_db
    def test_authenticated_user_allowed(self):
        user = BlogCustomerFactory()
        request = _request_with_user(user)
        assert IsUnbannedCustomer().has_permission(request, view=None) is True

    @pytest.mark.django_db
    def test_admin_user_also_passes(self):
        # IsUnbannedCustomer não distingue admin/customer — apenas auth.
        # O check específico de admin é IsClamaAdmin.
        admin = BlogUserFactory(is_clama_admin=True)
        request = _request_with_user(admin)
        assert IsUnbannedCustomer().has_permission(request, view=None) is True


@pytest.mark.django_db
class TestIsUnbannedCustomerWithBan:
    def test_banido_ativo_raises_permission_denied(self):
        c = BlogCustomerFactory()
        CustomerBanidoFactory(customer=c)
        request = _request_with_user(c)
        with pytest.raises(PermissionDenied) as exc_info:
            IsUnbannedCustomer().has_permission(request, view=None)
        detail = exc_info.value.detail
        assert detail.get("code") == "customer_banido"
        assert "pastoral_message" in detail

    def test_banimento_revogado_libera(self):
        c = BlogCustomerFactory()
        ban = CustomerBanidoFactory(customer=c)
        ban.revogado_em = timezone.now()
        ban.save()
        request = _request_with_user(c)
        assert IsUnbannedCustomer().has_permission(request, view=None) is True

    def test_admin_nao_e_afetado_mesmo_com_registro(self):
        # Edge case: admin cadastrado erroneamente como banido — ainda passa
        admin = BlogUserFactory(is_clama_admin=True)
        CustomerBanidoFactory(customer=admin)
        request = _request_with_user(admin)
        assert IsUnbannedCustomer().has_permission(request, view=None) is True

    def test_customer_sem_qualquer_ban_passa(self):
        c = BlogCustomerFactory()
        request = _request_with_user(c)
        assert IsUnbannedCustomer().has_permission(request, view=None) is True


@pytest.mark.django_db
class TestIsCommentOwner:
    def test_owner_has_object_permission(self):
        c = ComentarioFactory()
        request = _request_with_user(c.customer)
        assert (
            IsCommentOwner().has_object_permission(request, view=None, obj=c)
            is True
        )

    def test_non_owner_denied(self):
        c = ComentarioFactory()
        outro = BlogCustomerFactory()
        request = _request_with_user(outro)
        assert (
            IsCommentOwner().has_object_permission(request, view=None, obj=c)
            is False
        )

    def test_admin_not_automatic_owner(self):
        # Admin precisa de outro caminho (IsClamaAdmin OR IsCommentOwner via DRF
        # composition), não passa só por ser admin.
        c = ComentarioFactory()
        admin = BlogUserFactory(is_clama_admin=True)
        request = _request_with_user(admin)
        assert (
            IsCommentOwner().has_object_permission(request, view=None, obj=c)
            is False
        )

    def test_anonymous_denied_at_view_level(self):
        request = _request_with_user(AnonymousUser())
        assert IsCommentOwner().has_permission(request, view=None) is False
