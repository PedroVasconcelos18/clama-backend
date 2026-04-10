"""
Permissions customizadas para usuários.
"""

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
