"""
Permissions customizadas para usuários.
"""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


class IsClamaAdmin(BasePermission):
    """
    Permite acesso apenas a usuários admin do Clama.

    Usa a flag is_clama_admin do modelo User.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_clama_admin
        )


class IsCustomerPasswordCurrent(BasePermission):
    """
    Bloqueia o usuário customer que ainda tem `force_change_password=True`.
    A regra força a troca da senha temporária gerada pela saga freemium
    antes de permitir qualquer ação real.

    Default seguro (P-10): para usuários ANÔNIMOS o permission retorna
    `False` (negação). Em prática este permission é sempre composto com
    `IsAuthenticated` — qualquer combinador (AND/OR) trata o resultado
    corretamente. Mas, se algum dia for usado standalone por engano,
    "False para anônimo" é a postura defensiva certa: anonimo nunca tem
    sessão "current" pra começo.

    Quem está autenticado mas com a flag ativa recebe 403 pastoral.

    Isenções (NÃO usar este permission):
      - `POST /api/customer/auth/change-password/` — é o endpoint que zera
        a flag.
      - `GET /api/customer/me/` — frontend precisa ler o estado da flag para
        decidir o redirect, mesmo com a flag ativa.
      - `POST /api/customer/auth/logout/` e refresh — não realizam "trabalho
        real" do user; logout precisa funcionar mesmo com a flag ativa.

    Em G2.a, o único endpoint que realmente usa este permission é
    `POST /api/pedidos/` (paywall, em par com `IsAuthenticated`). Endpoints
    futuros que dependam de uma sessão "boa" do customer adotam-no por
    composição — sem permission global no settings.
    """

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            # P-10: nega anônimo por default. Compõe corretamente com
            # IsAuthenticated (AND): a 401 vem dele primeiro. Se este
            # permission for usado SOZINHO por engano, ainda nega — em vez
            # de "passar e quem decide é o caller".
            return False
        if getattr(user, "force_change_password", False):
            raise PermissionDenied(
                {
                    "error": {
                        "code": "force_change_password",
                        "message": "User must change password before continuing",
                        "pastoral_message": (
                            "Troque sua senha antes de continuar."
                        ),
                    }
                }
            )
        return True
