"""Escrita ancorada no espelho (Stories 3.9 e 3.10).

A janela que estas stories fecham: o post fica público **no instante da
publicação**; o espelho depende do webhook, que é assíncrono e pode falhar. É
justamente a janela em que o post é novo — quando o tráfego e a chance de
comentário são maiores. O primeiro leitor a comentar nela receberia erro de FK.
"""

from unittest.mock import Mock, patch

import pytest
import requests
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from clama.blog.models import (
    Comentario,
    PostEspelho,
    PostEspelhoStatus,
    PostStatus,
    Reacao,
)
from clama.blog.tests.factories import (
    BlogCustomerFactory,
    PostEspelhoFactory,
    PostFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def com_wordpress(settings):
    settings.WORDPRESS_API_URL = "https://wp-teste.clama.me"
    settings.WORDPRESS_API_USER = "clama-django-sync"
    settings.WORDPRESS_API_APP_PASSWORD = "chave-de-teste"


@pytest.fixture
def sem_wordpress(settings):
    settings.WORDPRESS_API_URL = ""
    settings.WORDPRESS_API_USER = ""
    settings.WORDPRESS_API_APP_PASSWORD = ""


def resposta_wp(posts):
    resposta = Mock(spec=requests.Response)
    resposta.status_code = 200
    resposta.json.return_value = posts
    resposta.headers = {"X-WP-TotalPages": "1"}
    resposta.raise_for_status.return_value = None
    return resposta


def post_wp(wp_id=101, slug="post-novo", status="publish"):
    return {
        "id": wp_id,
        "slug": slug,
        "title": {"raw": "Post novo"},
        "status": status,
        "date_gmt": "2026-08-03T12:00:00",
        "link": f"https://clama.me/blog/{slug}",
        "password": "",
    }


@pytest.fixture
def cliente_autenticado():
    """`APIClient` do DRF, não o do Django — as views são DRF e o client do
    Django não passa pela autenticação delas."""
    cliente = APIClient()
    cliente.force_authenticate(user=BlogCustomerFactory())
    return cliente


# Há validador de comprimento mínimo no serializer; texto curto vira 400 e
# esconderia o que estes testes querem medir.
COMENTARIO = "Obrigada por escrever isso, me ajudou hoje de manhã."


def url_comentarios(slug):
    return f"/api/blog/posts/{slug}/comments/"


def url_like(slug):
    return f"/api/blog/posts/{slug}/like/"


class TestResolucaoSobDemanda:
    """Story 3.10."""

    def test_comentario_em_post_sem_espelho_resolve_pela_api(
        self, cliente_autenticado, com_wordpress
    ):
        # AC1 e AC2. O webhook ainda não chegou; a escrita não pode presumir
        # o estado convergido.

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_wp([post_wp()])
            resposta = cliente_autenticado.post(
                url_comentarios("post-novo"),
                data={"conteudo": "Que texto bonito."},
                format="json",
            )

        assert resposta.status_code == 201
        comentario = Comentario.objects.get()
        assert comentario.post is None
        assert comentario.post_espelho.wp_post_id == 101

    def test_a_linha_criada_sob_demanda_e_identica_a_do_webhook(
        self, cliente_autenticado, com_wordpress
    ):
        # AC3. Se divergirem, a chegada do webhook viraria um segundo estado
        # em vez de convergência.

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_wp([post_wp()])
            cliente_autenticado.post(
                url_comentarios("post-novo"),
                data={"conteudo": COMENTARIO},
                format="json",
            )

        sob_demanda = PostEspelho.objects.get(wp_post_id=101)

        # Agora o mesmo post, pelo caminho do webhook.
        from clama.blog.tasks import sincronizar_post_espelho
        from clama.payments.models import WebhookEvento, WebhookProvider

        registro, _ = WebhookEvento.objects.try_register(
            provider=WebhookProvider.WORDPRESS,
            external_event_id="evt-101",
            event_type="post_publicado",
            payload={
                "wp_post_id": "101",
                "slug": "post-novo",
                "titulo": "Post novo",
                "status": "publish",
                "url": "https://clama.me/blog/post-novo",
                "published_at": "2026-08-03T12:00:00+00:00",
            },
        )
        sincronizar_post_espelho(str(registro.id))

        depois = PostEspelho.objects.get(wp_post_id=101)
        assert depois.id == sob_demanda.id
        assert depois.slug == sob_demanda.slug
        assert depois.titulo == sob_demanda.titulo
        assert depois.status == sob_demanda.status
        assert depois.published_at == sob_demanda.published_at
        assert depois.url == sob_demanda.url

    def test_webhook_posterior_atualiza_em_vez_de_duplicar(
        self, cliente_autenticado, com_wordpress
    ):
        # AC5.

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_wp([post_wp()])
            cliente_autenticado.post(
                url_comentarios("post-novo"),
                data={"conteudo": COMENTARIO},
                format="json",
            )

        from clama.blog.tasks import sincronizar_post_espelho
        from clama.payments.models import WebhookEvento, WebhookProvider

        registro, _ = WebhookEvento.objects.try_register(
            provider=WebhookProvider.WORDPRESS,
            external_event_id="evt-101",
            event_type="post_atualizado",
            payload={
                "wp_post_id": "101",
                "slug": "post-novo",
                "titulo": "Título editado",
                "status": "publish",
            },
        )
        sincronizar_post_espelho(str(registro.id))

        assert PostEspelho.objects.count() == 1
        assert PostEspelho.objects.get().titulo == "Título editado"
        # E o comentário continua ligado à mesma linha.
        assert Comentario.objects.get().post_espelho.titulo == "Título editado"

    def test_post_inexistente_no_wordpress_devolve_404_pastoral(
        self, cliente_autenticado, com_wordpress
    ):
        # AC4: erro tratado, nunca 500.

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_wp([])
            resposta = cliente_autenticado.post(
                url_comentarios("nao-existe"),
                data={"conteudo": COMENTARIO},
                format="json",
            )

        assert resposta.status_code == 404
        assert "pastoral_message" in str(resposta.content, "utf-8")

    def test_wordpress_indisponivel_nao_vira_404(
        self, cliente_autenticado, com_wordpress
    ):
        # A distinção que importa: "não consegui perguntar" ≠ "não existe".
        # Virar 404 aqui negaria comentário legítimo por falha de rede.

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.side_effect = requests.Timeout("caiu")
            with patch("clama.core.retry.time.sleep"):
                resposta = cliente_autenticado.post(
                    url_comentarios("post-novo"),
                    data={"conteudo": COMENTARIO},
                    format="json",
                )

        assert resposta.status_code != 404
        assert resposta.status_code >= 400

    def test_sem_wordpress_configurado_o_caminho_legado_segue_igual(
        self, cliente_autenticado, sem_wordpress
    ):
        # Ambiente sem WordPress: o CMS próprio continua funcionando como
        # antes, e um slug desconhecido é 404 — não 500 por tentar perguntar
        # a um WordPress que não existe.
        post = PostFactory(slug="post-legado", status=PostStatus.PUBLICADO)

        ok = cliente_autenticado.post(
            url_comentarios("post-legado"),
            data={"conteudo": COMENTARIO},
            format="json",
        )
        nao = cliente_autenticado.post(
            url_comentarios("nao-existe"),
            data={"conteudo": COMENTARIO},
            format="json",
        )

        assert ok.status_code == 201
        assert Comentario.objects.get().post_id == post.id
        assert nao.status_code == 404

    def test_corrida_com_o_webhook_nao_duplica(self, com_wordpress):
        # Duas resoluções simultâneas do mesmo post: a `UniqueConstraint` de
        # `wp_post_id` decide, e o savepoint impede que o INSERT perdedor
        # envenene a transação externa.
        from clama.blog.services.espelho import resolver_espelho

        with patch("clama.blog.services.wordpress_client.requests.get") as get:
            get.return_value = resposta_wp([post_wp()])
            primeiro = resolver_espelho("post-novo")
            segundo = resolver_espelho("post-novo")

        assert primeiro.id == segundo.id
        assert PostEspelho.objects.count() == 1


class TestEscritaRespeitaOStatus:
    """Story 3.9 — a garantia é server-side; o widget é conveniência."""

    @pytest.mark.parametrize(
        "status_espelho",
        [
            PostEspelhoStatus.RASCUNHO,
            PostEspelhoStatus.PRIVADO,
            PostEspelhoStatus.AGENDADO,
            PostEspelhoStatus.LIXEIRA,
            PostEspelhoStatus.PENDENTE,
        ],
    )
    def test_post_nao_publicado_recusa_comentario(
        self, cliente_autenticado, sem_wordpress, status_espelho
    ):
        # AC2. Cobre os cinco status não-públicos da tabela da Story 3.3.
        PostEspelhoFactory(slug="post-x", status=status_espelho)

        resposta = cliente_autenticado.post(
            url_comentarios("post-x"),
            data={"conteudo": COMENTARIO},
            format="json",
        )

        assert resposta.status_code == 409
        assert Comentario.objects.count() == 0

    def test_post_publicado_aceita(self, cliente_autenticado, sem_wordpress):
        PostEspelhoFactory(slug="post-x", status=PostEspelhoStatus.PUBLICADO)

        resposta = cliente_autenticado.post(
            url_comentarios("post-x"),
            data={"conteudo": COMENTARIO},
            format="json",
        )

        assert resposta.status_code == 201

    def test_despublicado_durante_a_escrita_devolve_409_pastoral(
        self, cliente_autenticado, sem_wordpress
    ):
        # AC3 e AC4. O caso real: a Juliana escreve um comentário longo, o
        # post é despublicado nesse meio-tempo, ela clica em enviar.
        #
        # 409 e não 403: não é falta de permissão dela, é estado do post — e o
        # frontend precisa distinguir para saber que deve **preservar o texto**
        # em vez de limpar a caixa.
        PostEspelhoFactory(slug="post-x", status=PostEspelhoStatus.PUBLICADO)

        PostEspelho.objects.filter(slug="post-x").update(
            status=PostEspelhoStatus.RASCUNHO
        )

        resposta = cliente_autenticado.post(
            url_comentarios("post-x"),
            data={"conteudo": "Texto longo que ela levou dez minutos escrevendo."},
            format="json",
        )

        assert resposta.status_code == 409
        # O handler pastoral aninha em `error` — é o envelope de três chaves
        # que o resto do projeto usa.
        corpo = resposta.json()["error"]
        assert corpo["code"] == "post_nao_aceita_interacao"
        # A mensagem fala com a Juliana, não com o console, e diz o que fazer
        # com o que ela digitou.
        assert "guarde" in corpo["pastoral_message"].lower()

    def test_o_espelho_vence_o_post_legado_no_estado(
        self, cliente_autenticado, sem_wordpress
    ):
        # Post migrado que foi despublicado no WordPress: o legado ainda diz
        # `publicado`, mas o WordPress é a fonte da verdade sobre o estado.
        PostFactory(slug="post-migrado", status=PostStatus.PUBLICADO)
        PostEspelhoFactory(slug="post-migrado", status=PostEspelhoStatus.LIXEIRA)

        resposta = cliente_autenticado.post(
            url_comentarios("post-migrado"),
            data={"conteudo": COMENTARIO},
            format="json",
        )

        assert resposta.status_code == 409
        assert Comentario.objects.count() == 0

    def test_like_tambem_respeita_o_status(self, cliente_autenticado, sem_wordpress):
        PostEspelhoFactory(slug="post-x", status=PostEspelhoStatus.RASCUNHO)

        resposta = cliente_autenticado.post(url_like("post-x"))

        assert resposta.status_code == 409
        assert Reacao.objects.count() == 0


class TestLikeNoEspelho:
    def test_like_em_post_do_wordpress_funciona(
        self, cliente_autenticado, sem_wordpress
    ):
        PostEspelhoFactory(slug="post-x", status=PostEspelhoStatus.PUBLICADO)

        resposta = cliente_autenticado.post(url_like("post-x"))

        assert resposta.status_code == 200
        assert resposta.json() == {"liked": True, "like_count": 1}
        assert Reacao.objects.get().post is None

    def test_toggle_encontra_o_like_gravado_no_espelho(
        self, cliente_autenticado, sem_wordpress
    ):
        # O filtro precisa casar a âncora que a linha realmente usa. Se
        # procurasse só por `post`, o segundo clique criaria um segundo like
        # em vez de remover o primeiro — e a `UniqueConstraint` responderia
        # com 500.
        PostEspelhoFactory(slug="post-x", status=PostEspelhoStatus.PUBLICADO)

        cliente_autenticado.post(url_like("post-x"))
        resposta = cliente_autenticado.post(url_like("post-x"))

        assert resposta.json() == {"liked": False, "like_count": 0}
        assert Reacao.objects.count() == 0


class TestAncoraObrigatoria:
    def test_comentario_sem_nenhuma_ancora_e_rejeitado_pelo_banco(self):
        # Relaxar as duas FKs para nullable abriria a porta para comentário
        # pendurado em nada — que nenhuma tela mostraria e nenhuma moderação
        # alcançaria. A `CheckConstraint` fecha.
        customer = BlogCustomerFactory()

        with pytest.raises(IntegrityError), transaction.atomic():
            Comentario.objects.create(
                post=None, post_espelho=None, customer=customer, conteudo=COMENTARIO
            )

    def test_reacao_sem_nenhuma_ancora_e_rejeitada(self):
        customer = BlogCustomerFactory()

        with pytest.raises(IntegrityError), transaction.atomic():
            Reacao.objects.create(post=None, post_espelho=None, customer=customer)
