"""Envia por Gmail apenas vagas analisadas ainda não notificadas.

Uso:
    python src/email_report.py --status
    python src/email_report.py --preview
    python src/email_report.py --send

O estado de envio fica em data/email_report_state.json.
Ele só é atualizado depois que o Gmail confirma o envio.
"""

import argparse
import base64
import json
import os
import webbrowser
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import httplib2
from dotenv import load_dotenv
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from relatorio_vagas import montar_html, buscar_vagas


RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

TOKEN = RAIZ / "credentials" / "gmail_token.json"
ESTADO = RAIZ / "data" / "email_report_state.json"
PREVIEW = RAIZ / "data" / "reports" / "email_preview.html"
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def carregar_estado():
    if not ESTADO.exists():
        return {"ids_enviados": [], "ultimo_envio": None}

    try:
        dados = json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise RuntimeError("O estado dos e-mails está inválido.") from erro

    ids = dados.get("ids_enviados", [])
    if not isinstance(ids, list) or not all(isinstance(item, int) for item in ids):
        raise RuntimeError("O estado dos e-mails está inválido.")

    return {
        "ids_enviados": ids,
        "ultimo_envio": dados.get("ultimo_envio"),
    }


def salvar_estado(ids):
    ESTADO.parent.mkdir(parents=True, exist_ok=True)

    dados = {
        "ids_enviados": sorted(set(ids)),
        "ultimo_envio": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    temporario = ESTADO.with_suffix(".json.tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporario, ESTADO)


def buscar_novas_vagas():
    estado = carregar_estado()
    enviados = set(estado["ids_enviados"])

    # Busca até 50 análises recentes já consideradas relevantes.
    vagas = buscar_vagas(limite=50, dias=30)
    novas = [vaga for vaga in vagas if int(vaga["id"]) not in enviados]

    # Mantém o e-mail enxuto.
    novas.sort(
        key=lambda vaga: (
            vaga.get("score_ia") or 0,
            vaga.get("data_analise_ia") or datetime.min,
        ),
        reverse=True,
    )

    return novas[:10], estado


def carregar_credenciais():
    if not TOKEN.is_file():
        raise RuntimeError(
            "Token do Gmail não encontrado. Execute gmail_auth.py novamente."
        )

    credenciais = Credentials.from_authorized_user_file(
        str(TOKEN),
        SCOPES,
    )

    if not credenciais.valid:
        if not credenciais.expired or not credenciais.refresh_token:
            raise RuntimeError("A autorização do Gmail não é válida.")

        credenciais.refresh(Request())

        temporario = TOKEN.with_suffix(".json.tmp")
        temporario.write_text(
            credenciais.to_json(),
            encoding="utf-8",
        )
        os.replace(temporario, TOKEN)

    return credenciais


def destinatario():
    destino = os.getenv("GMAIL_REPORT_TO", "").strip()
    if not destino:
        destino = os.getenv("GMAIL_ADDRESS", "").strip()

    if not destino or "@" not in destino or "\r" in destino or "\n" in destino:
        raise RuntimeError(
            "Configure GMAIL_REPORT_TO ou GMAIL_ADDRESS no .env."
        )

    return destino


def criar_html(vagas):
    html = montar_html(vagas, dias=30)
    return html.replace(
        "Relatório local",
        "Relatório por e-mail",
    ).replace(
        "Relatório gerado a partir do MySQL local. Nenhum e-mail foi enviado.",
        "Relatório automático do JobHunter AI.",
    )


def gerar_preview():
    vagas, _ = buscar_novas_vagas()

    if not vagas:
        print("Nenhuma vaga nova para enviar.")
        return None, 0

    html = criar_html(vagas)
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW.write_text(html, encoding="utf-8")

    print("Prévia gerada:", PREVIEW)
    print("Vagas novas na prévia:", len(vagas))
    webbrowser.open(PREVIEW.as_uri())

    return PREVIEW, len(vagas)


def enviar():
    vagas, estado = buscar_novas_vagas()

    if not vagas:
        print("Nenhuma vaga nova para enviar.")
        return 0

    destino = destinatario()
    credenciais = carregar_credenciais()

    mensagem = EmailMessage()
    mensagem["From"] = os.getenv("GMAIL_ADDRESS", "").strip()
    mensagem["To"] = destino
    mensagem["Subject"] = (
        f"JobHunter AI | {len(vagas)} vaga(s) nova(s) analisada(s)"
    )

    mensagem.set_content(
        "Seu cliente de e-mail não exibiu o relatório HTML.\n"
        "Abra esta mensagem em um cliente compatível com HTML."
    )

    mensagem.add_alternative(
        criar_html(vagas),
        subtype="html",
    )

    raw = base64.urlsafe_b64encode(
        mensagem.as_bytes()
    ).decode("ascii")

    http = AuthorizedHttp(
        credenciais,
        http=httplib2.Http(timeout=30),
    )

    servico = build(
        "gmail",
        "v1",
        http=http,
        cache_discovery=False,
    )

    resposta = (
        servico.users()
        .messages()
        .send(
            userId="me",
            body={"raw": raw},
        )
        .execute(num_retries=0)
    )

    # Só registra como enviado depois da confirmação do Gmail.
    todos_ids = list(estado["ids_enviados"])
    todos_ids.extend(int(vaga["id"]) for vaga in vagas)
    salvar_estado(todos_ids)

    print("Relatório enviado com sucesso.")
    print("Destinatário:", destino)
    print("Vagas enviadas:", len(vagas))
    print("ID Gmail:", resposta.get("id", "não informado"))

    return 0


def mostrar_status():
    vagas, estado = buscar_novas_vagas()

    print("\nJOBHUNTER AI — E-MAIL")
    print("Último envio:", estado.get("ultimo_envio") or "nenhum")
    print("Vagas já registradas como enviadas:", len(estado["ids_enviados"]))
    print("Vagas novas prontas para envio:", len(vagas))
    print("Nenhum e-mail foi enviado.")


def main():
    parser = argparse.ArgumentParser(
        description="Relatório por Gmail do JobHunter AI."
    )

    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--status", action="store_true")
    grupo.add_argument("--preview", action="store_true")
    grupo.add_argument("--send", action="store_true")

    args = parser.parse_args()

    try:
        if args.preview:
            gerar_preview()
            return 0

        if args.send:
            print(
                "ATENÇÃO: este comando enviará um e-mail real "
                "e registrará as vagas como notificadas."
            )
            if input("Digite ENVIAR para confirmar: ").strip() != "ENVIAR":
                print("Envio cancelado.")
                return 0
            return enviar()

        mostrar_status()
        return 0

    except HttpError as erro:
        print("Gmail retornou HTTP", erro.resp.status, ".")
        print("As vagas NÃO foram marcadas como enviadas.")
        return 1

    except RefreshError:
        print(
            "A autorização do Gmail expirou ou foi revogada. "
            "As vagas NÃO foram marcadas como enviadas."
        )
        return 1

    except (GoogleAuthError, RuntimeError, OSError, ValueError) as erro:
        if isinstance(erro, RuntimeError):
            print("Erro:", erro)
        else:
            print("Erro:", type(erro).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
