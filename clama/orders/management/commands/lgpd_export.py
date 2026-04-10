"""
Comando para exportar dados de um usuário conforme LGPD.

Usage:
    python manage.py lgpd_export --email usuario@email.com
"""

import json
import os
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from clama.orders.models import Pedido


class Command(BaseCommand):
    help = "Exporta todos os dados de pedidos de um usuário (LGPD - direito de acesso)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            required=True,
            help="E-mail do usuário para exportar dados",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default="lgpd_exports",
            help="Diretório para salvar o arquivo de export (default: lgpd_exports)",
        )

    def handle(self, *args, **options):
        email = options["email"].lower().strip()
        output_dir = options["output_dir"]

        self.stdout.write(f"Buscando pedidos para: {email}")

        # Busca todos os pedidos do email
        pedidos = Pedido.objects.filter(email=email).order_by("-created_at")
        count = pedidos.count()

        if count == 0:
            self.stdout.write(
                self.style.WARNING(f"Nenhum pedido encontrado para {email}")
            )
            return

        self.stdout.write(f"Encontrados {count} pedido(s)")

        # Monta estrutura de export
        export_data = {
            "meta": {
                "email": email,
                "export_date": datetime.now().isoformat(),
                "total_pedidos": count,
            },
            "pedidos": [],
        }

        for pedido in pedidos:
            pedido_data = {
                "id": str(pedido.id),
                "created_at": pedido.created_at.isoformat(),
                "updated_at": pedido.updated_at.isoformat(),
                # Dados pessoais (decifrados automaticamente pelo model)
                "nome": pedido.nome,
                "email": pedido.email,
                "telefone": pedido.telefone or None,
                "idade": pedido.idade,
                "sexo": pedido.sexo or None,
                # Conteúdo
                "pedido_oracao": pedido.pedido_oracao or None,
                "oracao_gerada": pedido.oracao_gerada or None,
                # Plano e valor
                "plano": {
                    "nome": pedido.plano.nome,
                    "valor_reais": pedido.plano.valor_reais_str,
                },
                "valor_reais": pedido.valor_reais_str,
                # Status e canal
                "status": pedido.status,
                "canal_entrega": pedido.canal_entrega,
                # Integração Asaas
                "asaas_charge_id": pedido.asaas_charge_id or None,
                # Consentimento
                "consent": {
                    "aceito": pedido.consent_aceito,
                    "versao": pedido.consent_versao or None,
                    "aceito_at": (
                        pedido.consent_aceito_at.isoformat()
                        if pedido.consent_aceito_at
                        else None
                    ),
                    "ip": pedido.consent_ip or None,
                },
            }
            export_data["pedidos"].append(pedido_data)

        # Cria diretório se não existir
        export_path = os.path.join(settings.BASE_DIR, output_dir)
        os.makedirs(export_path, exist_ok=True)

        # Salva arquivo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_email = email.replace("@", "_at_").replace(".", "_")
        filename = f"{safe_email}_{timestamp}.json"
        filepath = os.path.join(export_path, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        self.stdout.write(
            self.style.SUCCESS(f"Export salvo em: {filepath}")
        )
        self.stdout.write(
            self.style.WARNING(
                "ATENÇÃO: Este arquivo contém dados pessoais sensíveis. "
                "Manuseie com cuidado e exclua após enviar ao titular."
            )
        )
