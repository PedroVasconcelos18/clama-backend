"""Client da REST API do WordPress (Stories 3.5 e 4.1).

**Leitura no regime normal.** O Django não escreve no WordPress durante a
operação — o fluxo é o inverso: o WordPress avisa por webhook (Story 3.2) e o
Django espelha.

A escrita existe para **uma coisa só**: a exportação única do conteúdo legado
(Story 4.1), rodada por comando de management. Depois do Epic 4 esses métodos
não são chamados por caminho nenhum de request.

Credencial: **Application Password** de um usuário WordPress dedicado
(`clama-django-sync`), com o menor papel que atende leitura. São chaves de 24
caracteres do WordPress 5.6+, guardadas com hash bcrypt em user meta — o
WordPress nunca retém o texto puro depois da criação. Funcionam **apenas** para
chamadas de API, nunca para login no dashboard, e podem ser revogadas
individualmente sem trocar a senha do operador.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from django.conf import settings
from requests.auth import HTTPBasicAuth

from clama.core.exceptions import ClamaBaseException
from clama.core.retry import with_retry

logger = logging.getLogger("clama.blog.wordpress_client")

TIMEOUT_SEGUNDOS = 15
POR_PAGINA_MAX = 100
# 429 e 529 não são 5xx, mas são transientes — mesma lista do client do
# Mercado Pago.
STATUS_RETENTAVEIS = [429, 529]


class WordPressIndisponivel(ClamaBaseException):
    """Falha ao falar com a REST API do WordPress.

    Existe para que a reconciliação (Story 3.6) distinga "o WordPress disse
    que o post não existe" de "não consegui perguntar" — são conclusões
    opostas, e confundi-las apagaria vínculo de comentário por falha de rede.
    """

    code = "wordpress_indisponivel"
    message = "Não foi possível ler a API do WordPress."
    pastoral_message = "Estamos com dificuldade de falar com o blog agora."


class WordPressClient:
    """Leitura da REST API do WordPress com retry e log estruturado."""

    def __init__(
        self,
        base_url: str | None = None,
        usuario: str | None = None,
        senha: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.WORDPRESS_API_URL or "").rstrip("/")
        self._usuario = usuario or settings.WORDPRESS_API_USER
        self._senha = senha or settings.WORDPRESS_API_APP_PASSWORD

    @property
    def configurado(self) -> bool:
        return bool(self.base_url and self._usuario and self._senha)

    def _auth(self) -> HTTPBasicAuth:
        # Application Password usa Basic Auth sobre a REST API. O espaço a
        # cada 4 caracteres que o WordPress mostra na tela é cosmético e é
        # aceito pelo servidor, mas remover evita depender disso.
        return HTTPBasicAuth(self._usuario, self._senha.replace(" ", ""))

    @with_retry(
        max_attempts=3,
        backoff_seconds=[1, 2, 4],
        retriable_status_codes=STATUS_RETENTAVEIS,
    )
    def _get(self, caminho: str, **params) -> requests.Response:
        """GET com retry em rede, 5xx, 429 e 529.

        Devolve a `Response` inteira, não o JSON: a paginação do WordPress
        vive nos headers `X-WP-Total` e `X-WP-TotalPages`, e a reconciliação
        precisa deles para saber se a listagem veio completa.
        """
        url = f"{self.base_url}{caminho}"
        inicio = time.time()

        try:
            resposta = requests.get(
                url,
                params=params,
                auth=self._auth(),
                timeout=TIMEOUT_SEGUNDOS,
                headers={"Accept": "application/json"},
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.warning(
                "wordpress_api_erro_de_rede",
                extra={
                    "event": "wordpress_api_request",
                    "caminho": caminho,
                    "erro": str(exc),
                },
            )
            raise

        logger.info(
            "wordpress_api_request",
            extra={
                "event": "wordpress_api_request",
                "caminho": caminho,
                "status": resposta.status_code,
                "ms": round((time.time() - inicio) * 1000),
            },
        )
        resposta.raise_for_status()
        return resposta

    def listar_posts(
        self,
        *,
        pagina: int = 1,
        por_pagina: int = POR_PAGINA_MAX,
        status: str = "any",
    ) -> tuple[list[dict[str, Any]], int]:
        """Uma página de posts e o total de páginas segundo o WordPress.

        `status="any"` é necessário: o default da REST API é só `publish`, e
        a reconciliação precisa enxergar rascunho, lixeira e agendado — senão
        um post despublicado no WordPress ficaria `publicado` no espelho para
        sempre.

        Retorna `(posts, total_de_paginas)`. O total vem do header
        `X-WP-TotalPages`; a Story 3.6 usa isso para detectar listagem
        truncada em vez de concluir que os posts sumiram.
        """
        if not self.configurado:
            raise WordPressIndisponivel(
                message="WORDPRESS_API_URL/USER/APP_PASSWORD não configurados."
            )

        try:
            resposta = self._get(
                "/wp-json/wp/v2/posts",
                page=pagina,
                per_page=min(por_pagina, POR_PAGINA_MAX),
                status=status,
                # `context=edit` é o que devolve status não-público; exige a
                # capability de leitura do papel dedicado.
                context="edit",
                _fields="id,slug,title,status,date_gmt,link,password",
            )
        except requests.RequestException as exc:
            raise WordPressIndisponivel(
                message=f"Falha ao listar posts do WordPress: {exc}"
            ) from exc

        try:
            posts = resposta.json()
        except ValueError as exc:
            # Corpo não-JSON com 200 é o sintoma clássico de página de erro
            # do proxy ou de manutenção. Tratar como indisponível, não como
            # "zero posts".
            raise WordPressIndisponivel(
                message="Resposta do WordPress não é JSON."
            ) from exc

        if not isinstance(posts, list):
            raise WordPressIndisponivel(
                message="Resposta do WordPress não é uma lista de posts."
            )

        try:
            total_paginas = int(resposta.headers.get("X-WP-TotalPages", "1"))
        except ValueError:
            total_paginas = 1

        return posts, total_paginas

    def buscar_post_por_slug(self, slug: str) -> dict[str, Any] | None:
        """Um post pelo slug, ou `None` se o WordPress disser que não existe.

        `None` significa **o WordPress respondeu e não tem esse post**.
        Impossibilidade de perguntar levanta `WordPressIndisponivel` — são
        conclusões opostas, e confundi-las faria o Clama negar comentário por
        falha de rede.
        """
        if not self.configurado:
            raise WordPressIndisponivel(
                message="WORDPRESS_API_URL/USER/APP_PASSWORD não configurados."
            )

        try:
            resposta = self._get(
                "/wp-json/wp/v2/posts",
                slug=slug,
                status="any",
                context="edit",
                per_page=1,
                _fields="id,slug,title,status,date_gmt,link,password",
            )
        except requests.RequestException as exc:
            raise WordPressIndisponivel(
                message=f"Falha ao buscar post {slug!r} no WordPress: {exc}"
            ) from exc

        try:
            posts = resposta.json()
        except ValueError as exc:
            raise WordPressIndisponivel(
                message="Resposta do WordPress não é JSON."
            ) from exc

        if not isinstance(posts, list):
            raise WordPressIndisponivel(
                message="Resposta do WordPress não é uma lista de posts."
            )

        return posts[0] if posts else None

    # ------------------------------------------------------------------ #
    # Escrita — exclusiva da exportação do Epic 4.                        #
    # ------------------------------------------------------------------ #

    @with_retry(
        max_attempts=3,
        backoff_seconds=[1, 2, 4],
        retriable_status_codes=STATUS_RETENTAVEIS,
    )
    def _post(self, caminho: str, payload: dict) -> requests.Response:
        url = f"{self.base_url}{caminho}"
        inicio = time.time()

        try:
            resposta = requests.post(
                url,
                json=payload,
                auth=self._auth(),
                timeout=TIMEOUT_SEGUNDOS,
                headers={"Accept": "application/json"},
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.warning(
                "wordpress_api_erro_de_rede",
                extra={
                    "event": "wordpress_api_request",
                    "caminho": caminho,
                    "erro": str(exc),
                },
            )
            raise

        logger.info(
            "wordpress_api_request",
            extra={
                "event": "wordpress_api_request",
                "caminho": caminho,
                "metodo": "POST",
                "status": resposta.status_code,
                "ms": round((time.time() - inicio) * 1000),
            },
        )
        resposta.raise_for_status()
        return resposta

    def criar_ou_atualizar_post(
        self, *, wp_post_id: int | None, campos: dict[str, Any]
    ) -> dict[str, Any]:
        """Cria (POST) ou atualiza (POST no id) um post.

        A REST API do WordPress usa POST para os dois — não há PUT. Passar
        `wp_post_id` faz o endpoint virar `/posts/<id>`, que atualiza.
        """
        if not self.configurado:
            raise WordPressIndisponivel(
                message="WORDPRESS_API_URL/USER/APP_PASSWORD não configurados."
            )

        caminho = "/wp-json/wp/v2/posts"
        if wp_post_id:
            caminho = f"{caminho}/{wp_post_id}"

        try:
            resposta = self._post(caminho, campos)
        except requests.RequestException as exc:
            raise WordPressIndisponivel(
                message=f"Falha ao gravar post no WordPress: {exc}"
            ) from exc

        try:
            corpo = resposta.json()
        except ValueError as exc:
            raise WordPressIndisponivel(
                message="Resposta do WordPress não é JSON."
            ) from exc

        if not isinstance(corpo, dict) or "id" not in corpo:
            raise WordPressIndisponivel(
                message="Resposta do WordPress não traz o id do post."
            )

        return corpo
