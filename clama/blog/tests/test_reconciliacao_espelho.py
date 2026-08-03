"""Client do WordPress e reconciliação do espelho (Stories 3.5 e 3.6).

A guarda que estes testes protegem: **listagem incompleta, timeout ou 5xx
abortam a reconciliação**, nunca convergem para "o post não existe mais". Sem
isso, uma falha transitória do WordPress viraria remoção em massa de vínculo
de comentários.
"""

from datetime import UTC
from unittest.mock import Mock, patch

import pytest
import requests

from clama.blog.models import PostEspelho, PostEspelhoStatus
from clama.blog.services.wordpress_client import (
    WordPressClient,
    WordPressIndisponivel,
)
from clama.blog.tasks import reconciliar_espelho_com_wordpress
from clama.blog.tests.factories import ComentarioFactory, PostEspelhoFactory


@pytest.fixture
def com_credencial(settings):
    settings.WORDPRESS_API_URL = "https://wp-teste.clama.me"
    settings.WORDPRESS_API_USER = "clama-django-sync"
    settings.WORDPRESS_API_APP_PASSWORD = "abcd EFGH ijkl MNOP qrst UVWX"


def post_wp(wp_id: int, **campos) -> dict:
    base = {
        "id": wp_id,
        "slug": f"post-{wp_id}",
        "title": {"raw": f"Post {wp_id}"},
        "status": "publish",
        "date_gmt": "2026-08-03T10:00:00",
        "link": f"https://clama.me/blog/post-{wp_id}",
        "password": "",
    }
    base.update(campos)
    return base


def resposta_ok(posts: list[dict], total_paginas: int = 1) -> Mock:
    resposta = Mock(spec=requests.Response)
    resposta.status_code = 200
    resposta.json.return_value = posts
    resposta.headers = {"X-WP-TotalPages": str(total_paginas)}
    resposta.raise_for_status.return_value = None
    return resposta


class TestClient:
    def test_nao_configurado_e_detectavel_sem_chamar_a_rede(self, settings):
        settings.WORDPRESS_API_URL = ""
        settings.WORDPRESS_API_USER = ""
        settings.WORDPRESS_API_APP_PASSWORD = ""

        assert WordPressClient().configurado is False

    def test_o_espaco_da_application_password_e_removido(self, com_credencial):
        # O WordPress exibe a chave em grupos de 4 separados por espaço. O
        # servidor aceita com espaço, mas depender disso é depender de um
        # detalhe de apresentação.
        assert WordPressClient()._auth().password == "abcdEFGHijklMNOPqrstUVWX"

    def test_lista_posts_com_status_any(self, com_credencial):
        # O default da REST API é só `publish`. Sem `status=any`, um post
        # despublicado no WordPress ficaria `publicado` no espelho para
        # sempre — a reconciliação nunca o veria.
        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_ok([post_wp(1)])
            WordPressClient().listar_posts()

        assert get.call_args.kwargs["params"]["status"] == "any"
        assert get.call_args.kwargs["params"]["context"] == "edit"

    def test_devolve_o_total_de_paginas_do_header(self, com_credencial):
        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_ok([post_wp(1)], total_paginas=7)
            _posts, total = WordPressClient().listar_posts()

        assert total == 7

    def test_corpo_nao_json_com_200_vira_indisponivel(self, com_credencial):
        # Sintoma clássico de página de erro do proxy ou de manutenção.
        # Tratar como "zero posts" seria concluir que o blog inteiro sumiu.
        resposta = Mock(spec=requests.Response)
        resposta.status_code = 200
        resposta.json.side_effect = ValueError("not json")
        resposta.headers = {}
        resposta.raise_for_status.return_value = None

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta
            with pytest.raises(WordPressIndisponivel):
                WordPressClient().listar_posts()

    def test_json_que_nao_e_lista_vira_indisponivel(self, com_credencial):
        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_ok({"code": "rest_forbidden"})
            with pytest.raises(WordPressIndisponivel):
                WordPressClient().listar_posts()

    def test_timeout_vira_indisponivel(self, com_credencial):
        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.side_effect = requests.Timeout("estourou")
            with pytest.raises(WordPressIndisponivel):
                WordPressClient().listar_posts()

    def test_o_retry_do_projeto_e_usado(self, com_credencial):
        # AC6 da 3.5: usa `with_retry`, não retry inline. Três tentativas com
        # backoff [1,2,4] é a configuração do client do Mercado Pago.
        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.side_effect = requests.ConnectionError("caiu")
            with patch("clama.core.retry.time.sleep"):
                with pytest.raises(WordPressIndisponivel):
                    WordPressClient().listar_posts()

        assert get.call_count == 3


@pytest.mark.django_db
class TestReconciliacao:
    def test_early_return_quando_nao_ha_divergencia(self, com_credencial):
        # AC5. O caso comum é não haver nada a fazer; gravar mesmo assim
        # mexeria em `updated_at` de tudo a cada 15 minutos e poluiria
        # qualquer auditoria por data.
        from datetime import datetime

        # Data sem microssegundos: o `date_gmt` do WordPress não os tem, e a
        # comparação de igualdade acusaria divergência falsa.
        publicado = datetime(2026, 8, 3, 10, 0, 0, tzinfo=UTC)
        PostEspelhoFactory(
            wp_post_id=1,
            slug="post-1",
            titulo="Post 1",
            status=PostEspelhoStatus.PUBLICADO,
            url="https://clama.me/blog/post-1",
            published_at=publicado,
        )
        espelho = PostEspelho.objects.get(wp_post_id=1)
        atualizado_antes = espelho.updated_at

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_ok([post_wp(1)])
            contadores = reconciliar_espelho_com_wordpress()

        assert contadores["sem_mudanca"] == 1
        assert contadores["atualizados"] == 0
        espelho.refresh_from_db()
        assert espelho.updated_at == atualizado_antes

    def test_cria_espelho_de_post_que_o_webhook_perdeu(self, com_credencial):
        # AC1. É o cenário que justifica a task: o `wp_remote_post` falhou e
        # o WordPress não retenta.
        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_ok([post_wp(42)])
            contadores = reconciliar_espelho_com_wordpress()

        assert contadores["criados"] == 1
        assert PostEspelho.objects.get(wp_post_id=42).slug == "post-42"

    def test_corrige_status_divergente(self, com_credencial):
        PostEspelhoFactory(wp_post_id=5, status=PostEspelhoStatus.PUBLICADO)

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_ok([post_wp(5, status="draft")])
            contadores = reconciliar_espelho_com_wordpress()

        assert contadores["atualizados"] == 1
        assert PostEspelho.objects.get(wp_post_id=5).status == (
            PostEspelhoStatus.RASCUNHO
        )

    def test_e_idempotente(self, com_credencial):
        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_ok([post_wp(9)])
            primeiro = reconciliar_espelho_com_wordpress()
            segundo = reconciliar_espelho_com_wordpress()

        assert primeiro["criados"] == 1
        assert segundo["criados"] == 0
        assert segundo["sem_mudanca"] == 1
        assert PostEspelho.objects.count() == 1

    def test_devolve_dict_de_contadores(self, com_credencial):
        # AC6 da 3.6.
        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_ok([post_wp(1)])
            contadores = reconciliar_espelho_com_wordpress()

        assert set(contadores) == {
            "paginas_lidas",
            "posts_vistos",
            "criados",
            "atualizados",
            "sem_mudanca",
            "abortada",
            "motivo",
        }

    def test_pagina_todas_as_paginas(self, com_credencial):
        respostas = [
            resposta_ok([post_wp(1)], total_paginas=3),
            resposta_ok([post_wp(2)], total_paginas=3),
            resposta_ok([post_wp(3)], total_paginas=3),
        ]

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.side_effect = respostas
            contadores = reconciliar_espelho_com_wordpress()

        assert contadores["paginas_lidas"] == 3
        assert contadores["criados"] == 3


@pytest.mark.django_db
class TestGuardasDeAborto:
    """AC3 e AC4 — a parte que impede o desastre."""

    def test_wordpress_5xx_aborta_e_registra_motivo(self, com_credencial):
        erro = requests.HTTPError("500")
        erro.response = Mock(status_code=500)

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            resposta = Mock(spec=requests.Response)
            resposta.status_code = 500
            resposta.raise_for_status.side_effect = erro
            get.return_value = resposta
            with patch("clama.core.retry.time.sleep"):
                contadores = reconciliar_espelho_com_wordpress()

        assert contadores["abortada"] is True
        assert contadores["motivo"] == "wordpress_indisponivel"

    def test_5xx_nao_toca_no_espelho_existente(self, com_credencial):
        # A regra que importa: falha transitória **não pode** virar remoção
        # nem rebaixamento de status.
        PostEspelhoFactory(wp_post_id=7, status=PostEspelhoStatus.PUBLICADO)

        erro = requests.HTTPError("503")
        erro.response = Mock(status_code=503)

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            resposta = Mock(spec=requests.Response)
            resposta.status_code = 503
            resposta.raise_for_status.side_effect = erro
            get.return_value = resposta
            with patch("clama.core.retry.time.sleep"):
                reconciliar_espelho_com_wordpress()

        assert PostEspelho.objects.count() == 1
        assert PostEspelho.objects.get(wp_post_id=7).status == (
            PostEspelhoStatus.PUBLICADO
        )

    def test_listagem_incompleta_aborta_sem_aplicar_o_que_leu(self, com_credencial):
        # AC3. Aplicar as páginas que deram certo deixaria o espelho num
        # estado que nem o WordPress nem a rodada anterior descrevem — pior
        # que não fazer nada.
        respostas = [
            resposta_ok([post_wp(1)], total_paginas=3),
            requests.Timeout("caiu na segunda página"),
        ]

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.side_effect = respostas + [requests.Timeout()] * 10
            with patch("clama.core.retry.time.sleep"):
                contadores = reconciliar_espelho_com_wordpress()

        assert contadores["abortada"] is True
        assert PostEspelho.objects.count() == 0

    def test_teto_de_paginas_aborta_em_vez_de_truncar(self, com_credencial):
        # Se o WordPress alegar mais páginas do que o teto, a listagem está
        # incompleta e não sabemos o que ficou de fora.
        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_ok([post_wp(1)], total_paginas=9999)
            with patch("clama.blog.tasks.RECONCILIACAO_MAX_PAGINAS", 2):
                contadores = reconciliar_espelho_com_wordpress()

        assert contadores["abortada"] is True
        assert contadores["motivo"] == "listagem_incompleta"

    def test_post_ausente_da_resposta_nunca_e_removido(self, com_credencial):
        # AC4, e é o coração da story. O WordPress devolve uma lista sem o
        # post 8; isso **não** é motivo para apagar nada.
        PostEspelhoFactory(wp_post_id=8, status=PostEspelhoStatus.PUBLICADO)

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_ok([post_wp(99)])
            contadores = reconciliar_espelho_com_wordpress()

        assert contadores["abortada"] is False
        assert PostEspelho.objects.filter(wp_post_id=8).exists()
        assert PostEspelho.objects.get(wp_post_id=8).status == (
            PostEspelhoStatus.PUBLICADO
        )

    def test_comentarios_sobrevivem_a_reconciliacao_com_falha(self, com_credencial):
        espelho = PostEspelhoFactory(wp_post_id=8)
        ComentarioFactory(post_espelho=espelho, ip_address="198.51.100.4")

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.side_effect = requests.Timeout("caiu")
            with patch("clama.core.retry.time.sleep"):
                reconciliar_espelho_com_wordpress()

        assert espelho.comentarios.count() == 1
        assert espelho.comentarios.get().ip_address == "198.51.100.4"

    def test_sem_credencial_aborta_sem_chamar_a_rede(self, settings):
        settings.WORDPRESS_API_URL = ""
        settings.WORDPRESS_API_USER = ""
        settings.WORDPRESS_API_APP_PASSWORD = ""

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            contadores = reconciliar_espelho_com_wordpress()

        assert contadores["abortada"] is True
        assert contadores["motivo"] == "credencial_ausente"
        get.assert_not_called()


class TestCadenciaDocumentada:
    def test_a_task_esta_agendada_e_a_cadencia_esta_justificada(self, settings):
        # AC2: a frequência é o limite superior da janela de dessincronia, e
        # isso precisa estar escrito onde alguém que mexer no schedule leia.
        entrada = settings.CELERY_BEAT_SCHEDULE["blog-reconciliar-espelho-wordpress"]

        assert entrada["task"] == ("clama.blog.tasks.reconciliar_espelho_com_wordpress")

        from pathlib import Path

        base = Path(settings.BASE_DIR) / "config" / "settings" / "base.py"
        texto = base.read_text(encoding="utf-8")
        assert "limite superior da janela de dessincronia" in texto
