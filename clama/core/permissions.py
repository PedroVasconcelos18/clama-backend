"""
Permission classes compartilhadas entre apps.

`IsCustomerPasswordCurrent` é usada nos endpoints customer-facing pra
forçar a troca de senha temporária (gerada pela saga G1) antes de qualquer
ação significativa. Endpoints que precisam ficar acessíveis MESMO com a
flag ligada (`/me/`, `/change-password/`) NÃO devem incluir esta
permission.
"""

from rest_framework.permissions import BasePermission

from clama.core.exceptions import PastoralAPIException
from clama.core.pastoral_messages import MSG_CUSTOMER_FORCE_CHANGE_PASSWORD


class CustomerPasswordChangeRequiredError(PastoralAPIException):
    """403 retornado quando user autenticado precisa trocar senha temporária."""

    status_code = 403
    code = "customer_force_change_password"
    message = "User must change temporary password before continuing"
    pastoral_message = MSG_CUSTOMER_FORCE_CHANGE_PASSWORD


class IsCustomerPasswordCurrent(BasePermission):
    """
    Bloqueia ação se `request.user.force_change_password=True`.

    Levanta `CustomerPasswordChangeRequiredError` (403 pastoral) em vez de
    retornar False — caller distingue "não autenticado" (401) de "senha
    expirada" (403) sem precisar inspecionar o body do erro.

    Não-autenticados são deixados passar pra esta permission — combine com
    `IsAuthenticated` na view (`permission_classes = [IsAuthenticated,
    IsCustomerPasswordCurrent]`). Anonymous chega aqui com
    `request.user.is_authenticated == False` e `force_change_password` não
    se aplica.
    """

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return True
        if getattr(user, "force_change_password", False):
            raise CustomerPasswordChangeRequiredError()
        return True
