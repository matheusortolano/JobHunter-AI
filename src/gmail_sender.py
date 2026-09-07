"""Envio controlado de um e-mail de teste pelo Gmail OAuth."""

import argparse
import base64
import json
import os
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

import httplib2
from dotenv import load_dotenv
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")
TOKEN = RAIZ / "credentials" / "gmail_token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def endereco_valido(valor):
    nome, endereco = parseaddr(valor)
    return (
        bool(valor)
        and not nome
        and endereco == valor
        and "@" in endereco
        and not any(caractere.isspace() for caractere in valor)
        and "\r" not in valor
        and "\n" not in valor
    )


def verificar_configuracao():
    if not TOKEN.is_file():
        raise RuntimeError(
            "Token não encontrado. Execute python src/gmail_auth.py primeiro."
        )

    remetente = os.getenv("GMAIL_ADDRESS", "").strip()
    if not endereco_valido(remetente):
        raise RuntimeError("Configure GMAIL_ADDRESS no .env com seu Gmail.")

    try:
        dados = json.loads(TOKEN.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise RuntimeError("O arquivo de autorização está inválido.") from erro

    if not set(SCOPES).issubset(set(dados.get("scopes", []))):
        raise RuntimeError("O token não contém a permissão gmail.send.")

    return remetente


def carregar_credenciais():
    credenciais = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)

    if not credenciais.valid:
        if not credenciais.expired or not credenciais.refresh_token:
            raise RuntimeError("Autorização inválida. É necessário autorizar novamente.")

        credenciais.refresh(Request())
        temporario = TOKEN.with_suffix(".json.tmp")
        temporario.write_text(credenciais.to_json(), encoding="utf-8")
        os.replace(temporario, TOKEN)

    return credenciais


def enviar_teste(remetente):
    credenciais = carregar_credenciais()

    mensagem = EmailMessage()
    mensagem["From"] = remetente
    mensagem["To"] = remetente
    mensagem["Subject"] = "JobHunter AI | Teste de envio"
    mensagem.set_content(
        "Olá!\n\n"
        "O envio de e-mails do JobHunter AI está funcionando.\n\n"
        "Esta é apenas uma mensagem de teste. Nenhuma vaga foi analisada "
        "e nenhum relatório automático foi agendado.\n"
    )

    raw = base64.urlsafe_b64encode(mensagem.as_bytes()).decode("ascii")
    http = AuthorizedHttp(credenciais, http=httplib2.Http(timeout=30))
    servico = build("gmail", "v1", http=http, cache_discovery=False)
    resposta = (
        servico.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute(num_retries=0)
    )
    print("Gmail aceitou a mensagem de teste.")
    print("ID da mensagem:", resposta.get("id", "não informado"))
    print("Confira sua caixa de entrada e, se necessário, a pasta Enviados.")


def main():
    parser = argparse.ArgumentParser(description="Teste de envio do JobHunter.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--check", action="store_true", help="Verifica a configuração local.")
    grupo.add_argument("--send", action="store_true", help="Solicita confirmação e envia um teste.")
    args = parser.parse_args()

    try:
        remetente = verificar_configuracao()
        print("Configuração local encontrada.")
        print("Remetente e destinatário do teste:", remetente)

        if not args.send:
            print("Nenhuma API foi chamada e nenhum e-mail foi enviado.")
            return 0

        print("Será enviada UMA mensagem de teste para o endereço acima.")
        if input("Digite ENVIAR para confirmar: ").strip() != "ENVIAR":
            print("Envio cancelado.")
            return 0

        enviar_teste(remetente)
        return 0

    except HttpError as erro:
        print("Gmail retornou HTTP", erro.resp.status, ".")
        print("Nenhuma nova tentativa automática será realizada.")
        return 1
    except RefreshError:
        print("A autorização expirou ou foi revogada. Será necessário autorizar novamente.")
        return 1
    except (GoogleAuthError, RuntimeError, OSError, ValueError) as erro:
        if isinstance(erro, RuntimeError):
            print("Erro:", erro)
        else:
            print("Erro de autenticação ou conexão:", type(erro).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
