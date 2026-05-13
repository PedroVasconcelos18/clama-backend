"""Permission classes do app blog.

`IsUnbannedCustomer` — usar SEMPRE em endpoints customer (em vez de
`IsAuthenticated` cru). Versão básica desta story apenas checa autenticação;
a versão completa (que verifica `CustomerBanido`) virá na Story 5.2 quando
o model `CustomerBanido` existir (Story 5.1).

`IsCommentOwner` — permite operações object-level apenas pro dono do
comentário (PATCH/DELETE em /api/blog/comments/<id>/).
"""

from rest_framework.permissions import BasePermission


class IsUnbannedCustomer(BasePermission):
    """Customer autenticado e não-banido (versão básica).

    NOTA: esta versão NÃO checa banimento ainda — o model `CustomerBanido`
    será criado na Story 5.1 e esta classe será substituída pela versão
    completa na Story 5.2. Usar essa permission desde já garante que o
    upgrade não exija mudar callsite das ViewSets nas Stories 4.3 / 4.4.
    """

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)


class IsCommentOwner(BasePermission):
    """Permite operações object-level apenas pro dono do comentário."""

    def has_permission(self, request, view) -> bool:
        # Nível-view: precisa estar autenticado pra qualquer chance de owner.
        # O check de owner real fica em `has_object_permission`.
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        # `obj` é uma instância de Comentario; `obj.customer` é o User dono.
        return bool(
            getattr(obj, "customer_id", None) == getattr(request.user, "id", None)
        )
