"""Permission classes do app blog.

`IsUnbannedCustomer` (versão completa após Story 5.1) — usar SEMPRE em
endpoints customer (em vez de `IsAuthenticated` cru). Levanta 403 com
mensagem pastoral se o customer tem banimento ativo.

`IsCommentOwner` — permite operações object-level apenas pro dono do
comentário (PATCH/DELETE em /api/blog/comments/<id>/).
"""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


class IsUnbannedCustomer(BasePermission):
    """Customer autenticado e não-banido.

    - Anônimo → False (vira 401/403 default do DRF).
    - Admin (`is_clama_admin=True`) → True sem checar ban (admins moderam,
      não são moderados; edge-case: mesmo se houver registro de
      CustomerBanido, admin não é bloqueado pra que não fique trancado fora
      da própria função de moderação).
    - Customer com banimento ativo → levanta `PermissionDenied(403)` com
      `code=customer_banido` + `pastoral_message`.
    - Customer sem banimento ativo (ou com `revogado_em` setado) → True.
    """

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        # Admin tem caminho próprio (IsClamaAdmin); aqui só não bloqueamos.
        if getattr(user, "is_clama_admin", False):
            return True
        # Lazy import pra evitar circular import: models -> permissions
        # (via apps.ready chain).
        from .models import CustomerBanido

        is_banido = CustomerBanido.objects.filter(
            customer=user, revogado_em__isnull=True
        ).exists()
        if is_banido:
            raise PermissionDenied(
                detail={
                    "code": "customer_banido",
                    "pastoral_message": (
                        "Sua conta foi suspensa do sistema de comentários. "
                        "Entre em contato pelo nosso e-mail de suporte se "
                        "quiser entender o motivo."
                    ),
                }
            )
        return True


class IsCommentOwner(BasePermission):
    """Permite operações object-level apenas pro dono do comentário."""

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        return bool(
            getattr(obj, "customer_id", None) == getattr(request.user, "id", None)
        )
