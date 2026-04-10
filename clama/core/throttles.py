"""
Throttle classes customizadas para rate limiting.
"""

from rest_framework.throttling import SimpleRateThrottle


class EmailScopedThrottle(SimpleRateThrottle):
    """
    Throttle baseado em email para limitar criação de pedidos por email.

    Limita a 5 pedidos por hora por email para evitar spam de criação.
    Funciona mesmo para requisições anônimas (sem autenticação).
    """

    scope = "email_pedido"
    rate = "5/hour"

    def get_cache_key(self, request, view):
        """
        Usa o email do request como chave de cache.

        Se não houver email no request, não aplica throttle (retorna None).
        """
        email = self._get_email_from_request(request)
        if not email:
            return None

        # Normaliza email para lowercase
        email = email.lower().strip()

        return self.cache_format % {
            "scope": self.scope,
            "ident": email,
        }

    def _get_email_from_request(self, request) -> str | None:
        """
        Extrai email do body do request.

        Args:
            request: Request HTTP

        Returns:
            Email ou None se não encontrado
        """
        if hasattr(request, "data"):
            return request.data.get("email")
        return None
