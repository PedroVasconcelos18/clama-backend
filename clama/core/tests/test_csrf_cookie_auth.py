"""
CSRF nas escritas autenticadas por cookie (Story 1.7 / ADR-01).

Por que estes testes existem: autenticação por header era imune a CSRF por
construção — o navegador nunca anexa `Authorization` sozinho. Com cookie, ele
anexa, e o vetor nasce junto com a migração.

E o `SessionAuthentication` do default global NÃO cobre este caso: o DRF para na
primeira classe que autentica, e como a `CookieJWTAuthentication` devolve um
usuário, o `enforce_csrf` daquela nunca roda.

⚠️ `APIClient()` desliga a checagem de CSRF por padrão. Todo teste aqui usa
`enforce_csrf_checks=True` — sem isso o teste passa sem exercitar nada.
"""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()
SENHA = "Senha-Forte-12345!"


@pytest.fixture(autouse=True)
def _limpa_cache_entre_testes():
    """
    O throttle `customer_login` (5/min por IP) é backed por cache e acumula
    entre testes — todos usam o mesmo IP de client. Sem esta limpeza, os
    últimos testes do arquivo batem em 429 antes de conseguir logar.

    Mesmo padrão do `conftest.py` de `clama/customers/tests/`, que este
    diretório não herda.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="csrf@example.com", password=SENHA, nome_completo="Csrf Teste"
    )


def _login(client, email):
    resp = client.post(
        reverse("users:customer-login"),
        {"email": email, "password": SENHA},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    return resp


@pytest.mark.django_db
class TestCSRFEmEscritaAutenticada:
    def test_escrita_sem_token_de_csrf_e_rejeitada(self, customer):
        client = APIClient(enforce_csrf_checks=True)
        _login(client, customer.email)

        resp = client.patch(
            reverse("users:customer-me"),
            {"nome_format_blog": "compacto"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_escrita_com_token_de_csrf_passa(self, customer):
        client = APIClient(enforce_csrf_checks=True)
        _login(client, customer.email)

        token = client.get(reverse("core:csrf")).data["csrf_token"]
        resp = client.patch(
            reverse("users:customer-me"),
            {"nome_format_blog": "compacto"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_leitura_nao_exige_csrf(self, customer):
        client = APIClient(enforce_csrf_checks=True)
        _login(client, customer.email)

        assert (
            client.get(reverse("users:customer-me")).status_code == status.HTTP_200_OK
        )

    def test_erro_de_csrf_tem_mensagem_pastoral(self, customer):
        client = APIClient(enforce_csrf_checks=True)
        _login(client, customer.email)

        resp = client.patch(
            reverse("users:customer-me"),
            {"nome_format_blog": "compacto"},
            format="json",
        )
        corpo = resp.json()
        # Regra de ouro do projeto: toda resposta de erro tem pastoral_message.
        assert "pastoral_message" in corpo.get("error", corpo)


@pytest.mark.django_db
class TestEndpointDeCSRF:
    def test_devolve_token_e_seta_cookie(self, client):
        resp = client.get(reverse("core:csrf"))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["csrf_token"]
        assert settings.CSRF_COOKIE_NAME in resp.cookies

    def test_e_publico(self, client):
        """O widget precisa obter a prova antes de ter sessão."""
        assert client.get(reverse("core:csrf")).status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestEscopoDoCookie:
    """
    Story 1.4 / AC7 — o cookie não pode alcançar o servidor WordPress.

    O que impede isso é o atributo `Path=/api`: o navegador só envia o cookie
    em requisições cujo caminho começa com o path do cookie. `/blog/<slug>` não
    começa com `/api`, então a credencial nunca chega ao WordPress.

    O teste afirma o atributo, que é o mecanismo — o comportamento do navegador
    em si é verificado no gate de cutover (Story 6.5), com a aba de rede.
    """

    def test_cookies_tem_path_api(self, customer):
        client = APIClient()
        resp = _login(client, customer.email)

        for nome in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
            cookie = resp.cookies[nome]
            assert cookie["path"] == "/api", (
                f"{nome} com path {cookie['path']!r}: o cookie alcançaria /blog/* "
                "e entregaria a credencial ao servidor WordPress"
            )

    def test_cookies_sao_httponly_e_samesite_lax(self, customer):
        client = APIClient()
        resp = _login(client, customer.email)

        for nome in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
            cookie = resp.cookies[nome]
            # HttpOnly é o que tira o token do alcance de um XSS de plugin.
            assert cookie["httponly"], f"{nome} legível por JavaScript"
            assert cookie["samesite"] == "Lax"

    def test_cookies_nao_usam_atributo_domain(self, customer):
        """
        `Domain=.clama.me` entregaria o cookie ao WordPress em todo request —
        o oposto exato do que o ADR-01 existe para garantir.
        """
        client = APIClient()
        resp = _login(client, customer.email)

        for nome in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
            assert not resp.cookies[nome]["domain"]

    def test_cookie_de_csrf_tambem_fica_escopado_em_api(self, client):
        """
        O default do Django é `Path=/`, o que enviaria o cookie de CSRF também
        para `/blog/*` — entregando material de CSRF ao servidor WordPress, que
        é zona de confiança inferior, sem ganho: a verificação só roda em /api/.
        """
        resp = client.get(reverse("core:csrf"))
        assert resp.cookies[settings.CSRF_COOKIE_NAME]["path"] == "/api"

    def test_login_nao_devolve_token_no_corpo(self, customer):
        client = APIClient()
        resp = _login(client, customer.email)

        assert "access" not in resp.data
        assert "refresh" not in resp.data
        assert resp.data["user"]["email"] == customer.email
