"""Diff de URLs entre o Vike e o WordPress (Story 5.9).

**Compara a URL completa, não o slug.** A regra de ouro do SEO — manter o slug
— já está satisfeita: o padrão do Clama é `/blog/<slug>` e é o que o WordPress
usa. Mas slug igual **não é URL igual**:

- **barra final** — se o formato divergir entre as camadas, toda URL indexada
  recebe 301. Tratado na Story 5.2, verificado aqui.
- **paginação** — `?page=N` do Vike vira `/blog/page/N` no WordPress. Tratado
  na Story 5.6, verificado aqui.

A saída é a lista que o crawl de gate da **Story 6.5** consome.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from clama.blog.models import Post, PostEspelho, PostEspelhoStatus, PostStatus

TIMEOUT_SEGUNDOS = 15


class Command(BaseCommand):
    help = "Compara as URLs do blog entre o Vike (produção) e o WordPress."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base",
            default="",
            help="Base pública a sondar. Default: FRONTEND_PUBLIC_BLOG_BASE_URL.",
        )
        parser.add_argument(
            "--sondar",
            action="store_true",
            help="Além de comparar os inventários, faz GET em cada URL do "
            "Vike e registra o status. É o que prova o AC1 — 'URLs que hoje "
            "respondem 200', não 'URLs que deveriam responder'.",
        )
        parser.add_argument(
            "--json",
            dest="saida_json",
            default="",
            help="Grava o resultado em JSON. É este arquivo que a Story 6.5 "
            "consome como lista do crawl de gate.",
        )

    def handle(self, *args, **opcoes):
        base = (opcoes["base"] or settings.FRONTEND_PUBLIC_BLOG_BASE_URL or "").rstrip(
            "/"
        )

        if not base:
            self.stderr.write(self.style.ERROR("Base pública não configurada."))
            return

        do_vike = self._urls_do_vike(base)
        do_wordpress = self._urls_do_wordpress(base)

        relatorio = self._comparar(do_vike, do_wordpress)

        if opcoes["sondar"]:
            self._sondar(do_vike, relatorio)

        self._imprimir(relatorio, base)

        if opcoes["saida_json"]:
            with open(opcoes["saida_json"], "w", encoding="utf-8") as arquivo:
                json.dump(relatorio, arquivo, ensure_ascii=False, indent=2)
            self.stdout.write("")
            self.stdout.write(f"Lista para o gate da 6.5: {opcoes['saida_json']}")

    def _urls_do_vike(self, base: str) -> list[str]:
        """O que está no ar hoje: `/blog/<slug>`, sem barra final."""
        urls = [f"{base}/blog"]
        urls += [
            f"{base}/blog/{slug}"
            for slug in Post.objects.filter(status=PostStatus.PUBLICADO)
            .order_by("slug")
            .values_list("slug", flat=True)
        ]
        return urls

    def _urls_do_wordpress(self, base: str) -> list[str]:
        """O que o WordPress servirá, segundo o espelho.

        Só `PUBLICADO`. Rascunho e lixeira não respondem 200 em lugar nenhum,
        e incluí-los produziria divergência falsa.
        """
        urls = [f"{base}/blog"]
        urls += [
            f"{base}/blog/{slug}"
            for slug in PostEspelho.objects.filter(status=PostEspelhoStatus.PUBLICADO)
            .order_by("slug")
            .values_list("slug", flat=True)
        ]
        return urls

    def _comparar(self, vike: list[str], wordpress: list[str]) -> dict:
        so_no_vike = sorted(set(vike) - set(wordpress))
        so_no_wordpress = sorted(set(wordpress) - set(vike))

        return {
            "total_vike": len(vike),
            "total_wordpress": len(wordpress),
            "iguais": sorted(set(vike) & set(wordpress)),
            # URL que existe hoje e some depois = 404 no que estava indexado.
            # É a divergência que custa indexação.
            "some_no_cutover": so_no_vike,
            # URL nova não custa nada — só não estava indexada antes.
            "nasce_no_cutover": so_no_wordpress,
            "sondagem": {},
        }

    def _sondar(self, urls: list[str], relatorio: dict) -> None:
        """AC1: o inventário é do que **responde 200**, não do que deveria."""
        for url in urls:
            try:
                resposta = requests.get(
                    url, timeout=TIMEOUT_SEGUNDOS, allow_redirects=False
                )
                caminho = urlparse(url).path
                relatorio["sondagem"][caminho] = {
                    "status": resposta.status_code,
                    "location": resposta.headers.get("Location", ""),
                }
            except requests.RequestException as exc:
                relatorio["sondagem"][urlparse(url).path] = {
                    "status": 0,
                    "erro": type(exc).__name__,
                }

    def _imprimir(self, relatorio: dict, base: str) -> None:
        self.stdout.write("")
        self.stdout.write(f"Base: {base}")
        self.stdout.write(
            f"Vike: {relatorio['total_vike']} URLs  |  "
            f"WordPress: {relatorio['total_wordpress']} URLs  |  "
            f"iguais: {len(relatorio['iguais'])}"
        )

        # AC2: a comparação é de URL completa. Se a barra final divergisse, a
        # URL inteira mudaria e apareceria nas duas listas abaixo — é assim
        # que o diff de URL completa pega o que o diff de slug não pegaria.
        if relatorio["some_no_cutover"]:
            self.stdout.write("")
            self.stderr.write(
                self.style.ERROR(
                    f"{len(relatorio['some_no_cutover'])} URLs somem no cutover "
                    "— cada uma é um 404 no que já está indexado:"
                )
            )
            for url in relatorio["some_no_cutover"]:
                self.stderr.write(f"  {url}")

        if relatorio["nasce_no_cutover"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(relatorio['nasce_no_cutover'])} URLs nascem no cutover "
                    "(não custa indexação, mas confira se é intencional):"
                )
            )
            for url in relatorio["nasce_no_cutover"]:
                self.stdout.write(f"  {url}")

        if relatorio["sondagem"]:
            nao_200 = {
                caminho: dados
                for caminho, dados in relatorio["sondagem"].items()
                if dados["status"] != 200
            }
            self.stdout.write("")
            self.stdout.write(
                f"Sondagem: {len(relatorio['sondagem'])} URLs, "
                f"{len(nao_200)} fora de 200."
            )
            for caminho, dados in nao_200.items():
                destino = dados.get("location") or dados.get("erro", "")
                self.stdout.write(f"  [{dados['status']}] {caminho} {destino}")

        self.stdout.write("")
        if relatorio["some_no_cutover"]:
            # AC5: zero divergência não intencional é condição para seguir.
            self.stderr.write(
                self.style.ERROR(
                    "DIVERGÊNCIA. Resolva ou justifique cada URL acima antes do "
                    "cutover (AC5)."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("Nenhuma URL some no cutover."))
