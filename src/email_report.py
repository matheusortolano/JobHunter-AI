"""Relatórios do JobHunter por Gmail, com controle local de envio.

--status: consulta o MySQL e o histórico local, sem chamar o Gmail.
--preview: gera HTML local, sem enviar ou marcar vagas como notificadas.
--send: pede confirmação antes de enviar um relatório.
--run: envia sem confirmação, para uso no Agendador de Tarefas.

Um envio sem confirmação fica bloqueado para evitar repetição automática.
Consulte --status e a ajuda (--help) para resolver uma tentativa pendente.
Não apague o histórico, o marcador de inicialização ou o arquivo de trava.
"""

import argparse
import base64
import errno
import json
import os
import sys
import uuid
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from pathlib import Path

import httplib2
from dotenv import load_dotenv
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from database import conectar_banco
from relatorio_vagas import montar_html


RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")
TOKEN = RAIZ / "credentials" / "gmail_token.json"
ESTADO = RAIZ / "data" / "email_report_state.json"
MARCADOR = RAIZ / "data" / ".email_report_initialized"
TRAVA = RAIZ / "data" / ".email_report.lock"
PREVIEW = RAIZ / "data" / "reports" / "email_preview.html"
LOG = RAIZ / "data" / "logs" / "email_report.log"
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
LIMITE_EMAIL = 10
DIAS = 30


class EnvioEmExecucao(Exception):
    pass


class EnvioPendente(Exception):
    pass


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def registrar(mensagem):
    """Registra apenas mensagens controladas, nunca corpos de erros ou tokens."""
    print(mensagem, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as arquivo:
        arquivo.write(f"{agora()} | {mensagem}\n")


@contextmanager
def bloquear_envio():
    """Trava entre processos, liberada pelo sistema inclusive após um crash."""
    TRAVA.parent.mkdir(parents=True, exist_ok=True)
    # Não apagar o arquivo: dois processos poderiam travar arquivos distintos.
    with open(TRAVA, "a+b") as arquivo:
        descritor = arquivo.fileno()
        arquivo.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(descritor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descritor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as erro:
            if erro.errno in (errno.EACCES, errno.EAGAIN) or getattr(
                erro, "winerror", None
            ) in (33, 36):
                raise EnvioEmExecucao(
                    "Outra execução já está usando o envio. Nenhum e-mail foi enviado."
                ) from None
            raise
        try:
            yield
        finally:
            arquivo.seek(0)
            if os.name == "nt":
                msvcrt.locking(descritor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descritor, fcntl.LOCK_UN)


def novo_estado():
    return {"ids_enviados": [], "ultimo_envio": None, "pendente": None}


def validar_estado(dados):
    if not isinstance(dados, dict):
        raise ValueError("Estado inválido.")
    ids = dados.get("ids_enviados")
    if not isinstance(ids, list) or not all(
        type(item) is int and item > 0 for item in ids
    ):
        raise ValueError("Histórico de IDs inválido.")
    ultimo = dados.get("ultimo_envio")
    if ultimo is not None and not isinstance(ultimo, str):
        raise ValueError("Data do último envio inválida.")
    pendente = dados.get("pendente")
    if pendente is not None:
        if not isinstance(pendente, dict):
            raise ValueError("Tentativa pendente inválida.")
        obrigatorios = ("identificador", "ids", "destinatario", "assunto",
                        "message_id", "criado_em", "fase")
        if not all(isinstance(pendente.get(campo), str) and pendente[campo]
                   for campo in obrigatorios if campo != "ids"):
            raise ValueError("Tentativa pendente incompleta.")
        if pendente["fase"] not in ("preparado", "aceito"):
            raise ValueError("Fase de envio inválida.")
        if not isinstance(pendente.get("ids"), list) or not pendente["ids"] or not all(
            type(item) is int and item > 0 for item in pendente["ids"]
        ):
            raise ValueError("IDs da tentativa pendente inválidos.")
        if pendente["fase"] == "aceito" and not pendente.get("gmail_id"):
            raise ValueError("Confirmação do Gmail incompleta.")
    resultado = dict(dados)
    resultado["ids_enviados"] = sorted(set(ids))
    resultado["ultimo_envio"] = ultimo
    resultado["pendente"] = pendente
    return resultado


def carregar_estado():
    if not ESTADO.exists():
        if MARCADOR.exists():
            raise RuntimeError(
                "Histórico de e-mails ausente. Restaure o arquivo original; "
                "não zere o controle para continuar."
            )
        return novo_estado()
    try:
        dados = json.loads(ESTADO.read_text(encoding="utf-8"))
        estado = validar_estado(dados)
        # Também protege históricos antigos, anteriores a este marcador.
        MARCADOR.touch(exist_ok=True)
        return estado
    except (OSError, ValueError, TypeError):
        raise RuntimeError(
            "Histórico de e-mails inválido. Nenhum envio será realizado."
        ) from None


def salvar_estado(estado):
    estado = validar_estado(estado)
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    # Se ocorrer uma falha durante a primeira gravação, o histórico não
    # poderá ser recriado silenciosamente como se nunca houvesse envios.
    MARCADOR.touch(exist_ok=True)
    temporario = ESTADO.with_suffix(".json.tmp")
    with open(temporario, "w", encoding="utf-8") as arquivo:
        json.dump(estado, arquivo, ensure_ascii=False, indent=2)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    os.replace(temporario, ESTADO)


def buscar_novas_vagas(estado=None):
    """Busca todas as análises recentes antes de limitar o relatório a 10."""
    if estado is None:
        estado = carregar_estado()
    enviados = set(estado["ids_enviados"])
    conexao = conectar_banco()
    cursor = None
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, titulo, empresa, localizacao, url, score,
                   score_ia, recomendacao_ia, pontos_fortes_ia,
                   gaps_ia, justificativa_ia, data_analise_ia,
                   status_candidatura
            FROM vagas
            WHERE analisada_ia = TRUE
              AND score_ia IS NOT NULL
              AND recomendacao_ia IN ('CANDIDATAR', 'AVALIAR')
              AND data_analise_ia >= %s
            ORDER BY score_ia DESC, data_analise_ia DESC
            """,
            (datetime.now() - timedelta(days=DIAS),),
        )
        vagas = cursor.fetchall()
        return [
            vaga for vaga in vagas if int(vaga["id"]) not in enviados
        ][:LIMITE_EMAIL]
    finally:
        if cursor is not None:
            cursor.close()
        conexao.close()


def endereco_valido(valor):
    if not isinstance(valor, str) or not valor or any(c.isspace() for c in valor):
        return False
    nome, endereco = parseaddr(valor)
    return not nome and endereco == valor and endereco.count("@") == 1


def obter_enderecos():
    remetente = os.getenv("GMAIL_ADDRESS", "").strip()
    destino = os.getenv("GMAIL_REPORT_TO", "").strip() or remetente
    if not endereco_valido(remetente) or not endereco_valido(destino):
        raise RuntimeError("Confira GMAIL_ADDRESS e GMAIL_REPORT_TO no .env.")
    return remetente, destino


def carregar_credenciais():
    if not TOKEN.is_file():
        raise RuntimeError("Token do Gmail não encontrado. Execute gmail_auth.py.")
    credenciais = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not set(SCOPES).issubset(set(credenciais.scopes or [])):
        raise RuntimeError("O token não contém a permissão gmail.send.")
    if not credenciais.valid:
        if not credenciais.refresh_token:
            raise RuntimeError("Autorização inválida. Autorize o Gmail novamente.")
        credenciais.refresh(Request())
        temporario = TOKEN.with_suffix(".json.tmp")
        temporario.write_text(credenciais.to_json(), encoding="utf-8")
        os.replace(temporario, TOKEN)
    return credenciais


def criar_servico(credenciais):
    http = AuthorizedHttp(credenciais, http=httplib2.Http(timeout=30))
    return build("gmail", "v1", http=http, cache_discovery=False)


def criar_html(vagas):
    html = montar_html(vagas, dias=DIAS)
    return html.replace("Relatório local", "Relatório por e-mail").replace(
        "Relatório gerado a partir do MySQL local. Nenhum e-mail foi enviado.",
        "Relatório automático do JobHunter AI.",
    )


def criar_mensagem(vagas, remetente, destino):
    identificador = uuid.uuid4().hex
    message_id = make_msgid(idstring="jobhunter", domain="jobhunter.local")
    assunto = f"JobHunter AI | {len(vagas)} vaga(s) nova(s) analisada(s)"
    mensagem = EmailMessage()
    mensagem["From"] = remetente
    mensagem["To"] = destino
    mensagem["Subject"] = assunto
    mensagem["Message-ID"] = message_id
    mensagem["X-JobHunter-Report"] = identificador
    mensagem.set_content(
        "Seu cliente de e-mail não exibiu o relatório HTML. "
        "Abra esta mensagem em um cliente compatível com HTML."
    )
    mensagem.add_alternative(criar_html(vagas), subtype="html")
    raw = base64.urlsafe_b64encode(mensagem.as_bytes()).decode("ascii")
    pendente = {
        "identificador": identificador,
        "ids": [int(vaga["id"]) for vaga in vagas],
        "destinatario": destino,
        "assunto": assunto,
        "message_id": message_id,
        "criado_em": agora(),
        "fase": "preparado",
    }
    return raw, pendente


def finalizar_confirmado(estado):
    pendente = estado["pendente"]
    if not pendente or pendente["fase"] != "aceito":
        raise RuntimeError("Não existe envio confirmado para finalizar.")
    estado["ids_enviados"] = sorted(
        set(estado["ids_enviados"]) | set(pendente["ids"])
    )
    estado["ultimo_envio"] = agora()
    estado["ultimo_gmail_id"] = pendente.get("gmail_id")
    estado["pendente"] = None
    salvar_estado(estado)
    registrar("Histórico atualizado após confirmação do Gmail.")


def mostrar_pendente(pendente):
    print("Envio pendente:", pendente["identificador"])
    print("Fase:", pendente["fase"])
    print("Criado em:", pendente["criado_em"])
    print("Destinatário:", pendente["destinatario"])
    print("Vagas:", len(pendente["ids"]))
    print("Assunto:", pendente["assunto"])
    print("Message-ID:", pendente["message_id"])
    if pendente.get("gmail_id"):
        print("ID Gmail:", pendente["gmail_id"])
    if pendente["fase"] == "preparado":
        print("Confira Enviados/caixa de entrada antes de liberar outra tentativa.")
        print("Se confirmar a entrega: --confirm-delivered ID_DA_TENTATIVA")
        print("Se confirmar que não houve envio: --release-pending ID_DA_TENTATIVA")
        print("Nenhuma repetição automática será realizada enquanto houver dúvida.")


def executar_envio(automatico=False):
    with bloquear_envio():
        estado = carregar_estado()
        if estado["pendente"]:
            if estado["pendente"]["fase"] == "aceito":
                finalizar_confirmado(estado)
                return 0
            mostrar_pendente(estado["pendente"])
            raise EnvioPendente("Existe uma tentativa sem confirmação. Envio bloqueado.")

        vagas = buscar_novas_vagas(estado)
        if not vagas:
            registrar("Nenhuma vaga nova para enviar. Nenhum e-mail foi enviado.")
            return 0

        remetente, destino = obter_enderecos()
        if not automatico:
            print(f"Será enviado um relatório com {len(vagas)} vaga(s) para {destino}.")
            if input("Digite ENVIAR para confirmar: ").strip() != "ENVIAR":
                print("Envio cancelado.")
                return 0

        # Autenticação e criação do cliente ocorrem antes de reservar o envio.
        # Se a autorização expirou, não há tentativa de mensagem a resolver.
        credenciais = carregar_credenciais()
        servico = criar_servico(credenciais)
        raw, pendente = criar_mensagem(vagas, remetente, destino)

        # Registro durável ANTES de chamar messages.send.
        estado["pendente"] = pendente
        salvar_estado(estado)
        registrar(
            f"Tentativa {pendente['identificador']} preparada: "
            f"{len(vagas)} vaga(s)."
        )

        try:
            resposta = servico.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute(num_retries=0)
            gmail_id = resposta.get("id") if isinstance(resposta, dict) else None
            if not gmail_id:
                raise RuntimeError("Gmail não retornou um ID de confirmação.")
        except Exception as erro:
            status = erro.resp.status if isinstance(erro, HttpError) else None
            detalhe = f"HTTP {status}" if status is not None else type(erro).__name__
            registrar(f"Envio sem confirmação: {detalhe}. Nenhuma repetição automática.")
            raise EnvioPendente(
                "Não foi possível confirmar se o Gmail aceitou a mensagem. "
                "Consulte --status antes de qualquer nova tentativa."
            ) from None

        # Duas gravações: se a finalização falhar, a confirmação ainda poderá
        # ser recuperada sem reenviar a mensagem.
        pendente["fase"] = "aceito"
        pendente["gmail_id"] = str(gmail_id)
        salvar_estado(estado)
        finalizar_confirmado(estado)
        registrar(f"Relatório confirmado pelo Gmail: {len(vagas)} vaga(s).")
        return 0


def mostrar_status():
    with bloquear_envio():
        estado = carregar_estado()
        print("\nJOBHUNTER AI — E-MAIL")
        print("Último envio:", estado["ultimo_envio"] or "nenhum")
        print("Vagas já registradas como enviadas:", len(estado["ids_enviados"]))
        if estado["pendente"]:
            mostrar_pendente(estado["pendente"])
        else:
            vagas = buscar_novas_vagas(estado)
            print("Vagas novas prontas para envio:", len(vagas))
        print("Nenhum e-mail foi enviado.")


def gerar_preview():
    with bloquear_envio():
        estado = carregar_estado()
        if estado["pendente"]:
            mostrar_pendente(estado["pendente"])
            raise EnvioPendente("Resolva a tentativa pendente antes de gerar outra prévia.")
        vagas = buscar_novas_vagas(estado)
        if not vagas:
            print("Nenhuma vaga nova para enviar.")
            return 0
        PREVIEW.parent.mkdir(parents=True, exist_ok=True)
        temporario = PREVIEW.with_suffix(".html.tmp")
        temporario.write_text(criar_html(vagas), encoding="utf-8")
        os.replace(temporario, PREVIEW)
        print("Prévia gerada:", PREVIEW)
        print("Vagas novas na prévia:", len(vagas))
    webbrowser.open(PREVIEW.as_uri())
    return 0


def resolver_pendente(identificador, entregue):
    with bloquear_envio():
        estado = carregar_estado()
        pendente = estado["pendente"]
        if not pendente or pendente["identificador"] != identificador:
            raise RuntimeError("Tentativa não encontrada. Confira o ID em --status.")
        mostrar_pendente(pendente)
        if entregue:
            if input("Confirma que encontrou o e-mail enviado? Digite ENVIADO: ").strip() != "ENVIADO":
                print("Operação cancelada.")
                return 0
            pendente["fase"] = "aceito"
            pendente["gmail_id"] = pendente.get("gmail_id") or "confirmado-manualmente"
            salvar_estado(estado)
            finalizar_confirmado(estado)
            return 0

        if pendente["fase"] == "aceito":
            raise RuntimeError("O Gmail já confirmou este envio. Não é possível liberá-lo para repetição.")
        if input("Confirma que verificou e não encontrou o envio? Digite REENVIAR: ").strip() != "REENVIAR":
            print("Operação cancelada.")
            return 0
        estado["pendente"] = None
        salvar_estado(estado)
        registrar("Tentativa liberada manualmente. Nenhum e-mail foi enviado agora.")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Relatórios do JobHunter por Gmail.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--status", action="store_true")
    grupo.add_argument("--preview", action="store_true")
    grupo.add_argument("--send", action="store_true", help="Envio manual com confirmação.")
    grupo.add_argument("--run", action="store_true", help="Envio automático, sem confirmação.")
    grupo.add_argument("--confirm-delivered", metavar="ID")
    grupo.add_argument("--release-pending", metavar="ID")
    args = parser.parse_args()
    try:
        if args.preview:
            return gerar_preview()
        if args.send:
            return executar_envio(automatico=False)
        if args.run:
            return executar_envio(automatico=True)
        if args.confirm_delivered:
            return resolver_pendente(args.confirm_delivered, entregue=True)
        if args.release_pending:
            return resolver_pendente(args.release_pending, entregue=False)
        mostrar_status()
        return 0
    except EnvioEmExecucao as erro:
        print(erro)
        return 1
    except EnvioPendente as erro:
        print(erro)
        return 2
    except RefreshError:
        registrar("Autorização do Gmail expirada ou revogada. Reautorize manualmente.")
        return 3
    except HttpError as erro:
        registrar(f"Gmail retornou HTTP {erro.resp.status}. Nenhum retry automático.")
        return 1
    except (GoogleAuthError, RuntimeError, OSError, ValueError) as erro:
        # Nunca imprimir o corpo bruto de exceções de APIs ou de autenticação.
        if isinstance(erro, RuntimeError):
            print("Erro:", erro)
        else:
            print("Erro:", type(erro).__name__)
        return 1
    except KeyboardInterrupt:
        print("Interrompido. Consulte --status antes de tentar novamente.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
