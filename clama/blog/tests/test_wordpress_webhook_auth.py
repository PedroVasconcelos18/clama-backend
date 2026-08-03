"""Autenticação HMAC do webhook do WordPress (Story 3.2).

O endpoint alcança comentários e IPs sob retenção legal. Estes testes são a
fronteira entre "só o nosso WordPress escreve" e "qualquer um escreve".
"""

import hashlib
import hmac
from unittest.mock import patch

import pytest
from django.urls import reverse

from clama.blog.services.wordpress_webhook import verificar_assinatura_webhook

SEGREDO = "segredo-de-teste-do-webhook"
URL = "/api/webhooks/wordpress/"


@pytest.fixture
def com_segredo(settings):
    """Segredo configurado — o estado normal de produção."""
    settings.WORDPRESS_WEBHOOK_SECRET = SEGREDO
    return SEGREDO


@pytest.fixture
def sem_segredo(settings):
    settings.WORDPRESS_WEBHOOK_SECRET = ""


def assinar(corpo: bytes, segredo: str = SEGREDO) -> str:
    return hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


CORPO = (
    "evento_id=abc-1&tipo=post_publicado&wp_post_id=7&slug=oi&titulo=Oi&status=publish"
)
TIPO_FORM = "application/x-www-form-urlencoded"


class TestMiddleware:
    def test_assinatura_valida_passa(self, client, db, com_segredo):
        resposta = client.post(
            URL,
            data=CORPO,
            content_type=TIPO_FORM,
            HTTP_X_CLAMA_SIGNATURE=assinar(CORPO.encode()),
        )

        assert resposta.status_code == 200

    def test_assinatura_ausente_devolve_401(self, client, db, com_segredo):
        resposta = client.post(URL, data=CORPO, content_type=TIPO_FORM)

        assert resposta.status_code == 401
        assert resposta.json()["error"]["code"] == "unauthorized"
        # Envelope pastoral de três chaves, como o resto do projeto.
        assert "pastoral_message" in resposta.json()["error"]

    def test_assinatura_invalida_devolve_401(self, client, db, com_segredo):
        resposta = client.post(
            URL,
            data=CORPO,
            content_type=TIPO_FORM,
            HTTP_X_CLAMA_SIGNATURE="a" * 64,
        )

        assert resposta.status_code == 401

    def test_assinatura_de_outro_corpo_nao_serve(self, client, db, com_segredo):
        # É o ponto do HMAC sobre corpo cru: interceptar uma assinatura
        # legítima não permite trocar o payload.
        assinatura_de_outro = assinar(b"evento_id=outro&tipo=post_publicado")

        resposta = client.post(
            URL,
            data=CORPO,
            content_type=TIPO_FORM,
            HTTP_X_CLAMA_SIGNATURE=assinatura_de_outro,
        )

        assert resposta.status_code == 401

    def test_assinatura_com_prefixo_sha256_e_aceita(self, client, db, com_segredo):
        # `hash_hmac` do PHP nos exemplos canônicos de webhook produz
        # `sha256=<hex>`. Recusar o prefixo daria um bug que só aparece em
        # produção.
        resposta = client.post(
            URL,
            data=CORPO,
            content_type=TIPO_FORM,
            HTTP_X_CLAMA_SIGNATURE=f"sha256={assinar(CORPO.encode())}",
        )

        assert resposta.status_code == 200

    def test_assinatura_nao_ascii_nao_derruba_o_processo(self, client, db, com_segredo):
        # `compare_digest` levanta TypeError com não-ASCII, e a assinatura vem
        # do atacante. Sem o try/except isso seria 500, não 401.
        resposta = client.post(
            URL,
            data=CORPO,
            content_type=TIPO_FORM,
            HTTP_X_CLAMA_SIGNATURE="assinatura-com-acentuação-é",
        )

        assert resposta.status_code == 401

    def test_o_middleware_nao_quebra_o_corpo_para_a_view(self, client, db, com_segredo):
        # AC7. O middleware lê `request.body` para conferir o HMAC; se
        # consumisse o stream, a view receberia corpo vazio e devolveria 400.
        from clama.payments.models import WebhookEvento

        resposta = client.post(
            URL,
            data=CORPO,
            content_type=TIPO_FORM,
            HTTP_X_CLAMA_SIGNATURE=assinar(CORPO.encode()),
        )

        assert resposta.status_code == 200
        registro = WebhookEvento.objects.get(external_event_id="abc-1")
        assert registro.payload["wp_post_id"] == "7"

    def test_outras_rotas_passam_sem_assinatura(self, client, db, com_segredo):
        # Fast-path: o middleware só olha o próprio path.
        resposta = client.get(reverse("blog-post-public-list"))

        assert resposta.status_code != 401


class TestSegredoNaoConfigurado:
    def test_sem_segredo_tudo_e_401(self, client, db, sem_segredo):
        # Falha fechada: sem segredo, ninguém escreve. O contrário abriria o
        # endpoint em qualquer ambiente que esquecesse a env var.
        resposta = client.post(
            URL,
            data=CORPO,
            content_type=TIPO_FORM,
            HTTP_X_CLAMA_SIGNATURE=assinar(CORPO.encode()),
        )

        assert resposta.status_code == 401


class TestNaoViraVetorDeCarga:
    def test_assinatura_invalida_nao_cria_webhook_evento(self, client, db, com_segredo):
        # AC2. Sem isto, qualquer um faria o Clama gravar linha e enfileirar
        # task mandando POST — o endpoint viraria amplificador.
        from clama.payments.models import WebhookEvento

        client.post(
            URL,
            data=CORPO,
            content_type=TIPO_FORM,
            HTTP_X_CLAMA_SIGNATURE="invalida",
        )

        assert WebhookEvento.objects.count() == 0

    def test_assinatura_invalida_nao_enfileira_task(self, client, db, com_segredo):
        with patch("clama.blog.tasks.sincronizar_post_espelho.delay") as espiao:
            client.post(
                URL,
                data=CORPO,
                content_type=TIPO_FORM,
                HTTP_X_CLAMA_SIGNATURE="invalida",
            )

        espiao.assert_not_called()


class TestFuncaoCanonica:
    """A função é a fonte da verdade; middleware e futuros consumidores usam
    a mesma, para não divergirem."""

    def test_valida_corpo_cru(self, rf, com_segredo):
        corpo = b"qualquer=coisa"
        req = rf.post(
            URL,
            data=corpo,
            content_type=TIPO_FORM,
            HTTP_X_CLAMA_SIGNATURE=assinar(corpo),
        )

        assert verificar_assinatura_webhook(req) is True

    def test_nunca_levanta(self, rf, com_segredo):
        # Contrato: retorna False em toda falha. Levantar aqui viraria 500
        # num caminho que o atacante controla.
        req = rf.post(URL, data=b"x", content_type=TIPO_FORM)

        assert verificar_assinatura_webhook(req) is False

    @pytest.mark.parametrize("segredo_errado", ["outro-segredo", "x"])
    def test_segredo_diferente_nao_valida(self, rf, com_segredo, segredo_errado):
        corpo = b"evento_id=1"
        req = rf.post(
            URL,
            data=corpo,
            content_type=TIPO_FORM,
            HTTP_X_CLAMA_SIGNATURE=assinar(corpo, segredo_errado),
        )

        assert verificar_assinatura_webhook(req) is False
