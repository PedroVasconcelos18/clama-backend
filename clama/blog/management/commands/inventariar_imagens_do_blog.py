"""Inventário e verificação das imagens dos posts (Story 4.2).

⚠️ **A premissa do épico está errada, e isto está verificado no código.**

O `WP-FR27` e o risco **R16** afirmam que os posts referenciam imagens servidas
pelo Django (`clama-backend/media/`) e que elas quebrariam no
descomissionamento. Não é o caso:

- não existe `ImageField` nem `FileField` no app `blog`;
- não existe endpoint de upload de blog — `blog/views.py` usa só o parser JSON;
- `Post.imagem_capa_url` é `URLField`, isto é, string;
- o sanitizador restringe `img` a `src`/`alt`/`title` e os protocolos a
  `http`/`https`, então **`src` relativo é removido pelo bleach** — só absoluto
  sobrevive. O frontend impõe o mesmo na entrada.

Consequência: **não há mídia de blog no Django para migrar**, e nada quebra no
descomissionamento. O risco R16 não se aplica.

O que sobra, e que este comando faz, é o risco **real**: link podre externo.
Uma imagem hospedada em serviço temporário ou em conta pessoal é fragilidade
independente da migração — e o cutover não pode acontecer com imagem pendente.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

import requests
from django.core.management.base import BaseCommand

from clama.blog.models import Post, PostStatus

TIMEOUT_SEGUNDOS = 10

# `src` de `<img>` no corpo. O bleach já garantiu que só há absoluto http(s);
# o regex não precisa lidar com relativo.
PADRAO_IMG = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


class Command(BaseCommand):
    help = "Inventaria e verifica as imagens referenciadas nos posts do blog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--verificar",
            action="store_true",
            help="Além de inventariar, faz HEAD em cada URL. Sem isto, só "
            "lista — útil para inspecionar hosts sem gastar rede.",
        )
        parser.add_argument(
            "--somente-publicados",
            action="store_true",
            help="Só posts publicados. É o conjunto que o AC5 exige íntegro "
            "antes do cutover; rascunho com imagem podre não bloqueia nada.",
        )

    def handle(self, *args, **opcoes):
        posts = Post.objects.all()
        if opcoes["somente_publicados"]:
            posts = posts.filter(status=PostStatus.PUBLICADO)

        # slug → [(origem, url)]
        referencias: list[tuple[str, str, str]] = []

        for post in posts.only("slug", "conteudo_html", "imagem_capa_url"):
            if post.imagem_capa_url:
                referencias.append((post.slug, "capa", post.imagem_capa_url))
            for url in PADRAO_IMG.findall(post.conteudo_html or ""):
                referencias.append((post.slug, "corpo", url))

        if not referencias:
            self.stdout.write(
                self.style.SUCCESS(
                    "Nenhuma imagem referenciada. Nada a migrar nem a verificar."
                )
            )
            return

        self._inventario(referencias)

        if opcoes["verificar"]:
            self._verificar(referencias)

    def _inventario(self, referencias):
        """AC1: de onde cada imagem é servida hoje."""
        hosts = Counter(
            urlparse(url).netloc or "(relativo)" for _, _, url in referencias
        )

        self.stdout.write("")
        self.stdout.write(f"{len(referencias)} referências de imagem em posts.")
        self.stdout.write("")
        self.stdout.write("Hosts:")
        for host, quantas in hosts.most_common():
            self.stdout.write(f"  {quantas:>4}  {host}")

        # O achado que interessa: host que não controlamos é fragilidade, e é
        # a razão real desta story existir depois que a premissa caiu.
        proprios = {"clama.me", "www.clama.me", "api.clama.me"}
        terceiros = {h: q for h, q in hosts.items() if h not in proprios}

        if terceiros:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Hospedados fora do domínio do Clama — link podre aqui "
                    "quebra o post sem aviso:"
                )
            )
            for host, quantas in sorted(terceiros.items(), key=lambda x: -x[1]):
                self.stdout.write(f"  {quantas:>4}  {host}")

    def _verificar(self, referencias):
        """AC2 a AC5: toda imagem responde 200, e o que falha tem nome."""
        self.stdout.write("")
        self.stdout.write("Verificando…")

        falhas: list[tuple[str, str, str, str]] = []
        vistas: set[str] = set()

        for slug, origem, url in referencias:
            if url in vistas:
                continue
            vistas.add(url)

            try:
                # HEAD primeiro; alguns CDNs recusam HEAD e respondem a GET.
                resposta = requests.head(
                    url, timeout=TIMEOUT_SEGUNDOS, allow_redirects=True
                )
                if resposta.status_code >= 400:
                    resposta = requests.get(
                        url, timeout=TIMEOUT_SEGUNDOS, allow_redirects=True, stream=True
                    )
                    resposta.close()
                situacao = str(resposta.status_code)
                ok = resposta.status_code < 400
            except requests.RequestException as exc:
                situacao = type(exc).__name__
                ok = False

            if not ok:
                falhas.append((slug, origem, url, situacao))

        self.stdout.write("")
        self.stdout.write(f"{len(vistas)} URLs únicas verificadas.")

        if not falhas:
            self.stdout.write(
                self.style.SUCCESS(
                    "Todas responderam 200. O cutover não está bloqueado por imagem."
                )
            )
            return

        # AC4: nominalmente. AC5: bloqueia o cutover.
        self.stdout.write("")
        self.stderr.write(self.style.ERROR(f"{len(falhas)} imagens não responderam:"))
        for slug, origem, url, situacao in falhas:
            self.stderr.write(f"  [{situacao}] {slug} ({origem}): {url}")
        self.stdout.write("")
        self.stderr.write(
            self.style.ERROR(
                "Migração INCOMPLETA. O cutover não pode acontecer com imagem "
                "pendente (AC5)."
            )
        )
