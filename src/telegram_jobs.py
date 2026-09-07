"""Relatório de vagas do JobHunter para o Matheus AI Hub.

--status: consulta vagas e histórico, sem enviar mensagens.
--preview: mostra as mensagens que seriam enviadas, sem enviar.
--send: envia após confirmação explícita.
--run: envio sem confirmação, reservado para um agendamento futuro.

O histórico do Telegram é independente do Gmail. Uma tentativa de envio
incerta fica bloqueada para evitar duplicações automáticas. Não apague o
banco local nem o arquivo de trava para tentar contornar esse bloqueio.
"""

import argparse
import errno
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from database import conectar_banco
from hub_bridge import enviar_notificacao, verificar_hub


RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")
DADOS = RAIZ / "data"
HISTORICO = DADOS / "telegram_jobs.sqlite3"
MARCADOR = DADOS / ".telegram_jobs_initialized"
TRAVA = DADOS / ".telegram_jobs.lock"
DIAS = 30


class EnvioBloqueado(RuntimeError):
    pass


def configuracao():
    try:
        minimo = int(os.getenv("TELEGRAM_MIN_SCORE", "60"))
        limite = int(os.getenv("TELEGRAM_BATCH_LIMIT", "5"))
    except ValueError:
        raise RuntimeError("Os limites do Telegram devem ser números inteiros.") from None
    if not 0 <= minimo <= 100 or not 1 <= limite <= 10:
        raise RuntimeError("Use score entre 0 e 100 e lote entre 1 e 10.")
    return minimo, limite


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def bloquear_envio():
    """Trava entre processos; o sistema libera a trava após um crash."""
    DADOS.mkdir(parents=True, exist_ok=True)
    with open(TRAVA, "a+b") as arquivo:
        arquivo.seek(0)
        fd = arquivo.fileno()
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as erro:
            if erro.errno in (errno.EACCES, errno.EAGAIN) or getattr(
                erro, "winerror", None
            ) in (33, 36):
                raise EnvioBloqueado("Outra execução já está enviando notificações.") from None
            raise
        try:
            yield
        finally:
            arquivo.seek(0)
            if os.name == "nt":
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)


def abrir_historico(criar=False):
    """Abre o histórico; consultas de status nunca criam um novo banco."""
    if not HISTORICO.exists():
        if MARCADOR.exists():
            raise RuntimeError(
                "Histórico do Telegram ausente. Restaure o arquivo original; "
                "não zere o controle para continuar."
            )
        if not criar:
            return None
        DADOS.mkdir(parents=True, exist_ok=True)
        MARCADOR.touch(exist_ok=True)

    if criar:
        conexao = sqlite3.connect(HISTORICO, timeout=5)
    else:
        conexao = sqlite3.connect(
            HISTORICO.resolve().as_uri() + "?mode=ro", uri=True, timeout=5
        )
    try:
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA busy_timeout=5000")
        if criar:
            conexao.execute(
                """CREATE TABLE IF NOT EXISTS entregas (
                    vaga_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL CHECK (
                        status IN ('preparado', 'enviado', 'incerto')
                    ),
                    preparado_em TEXT NOT NULL,
                    enviado_em TEXT
                )"""
            )
            conexao.commit()
        else:
            # Impede que um arquivo de histórico vazio seja aceito como válido.
            conexao.execute("SELECT vaga_id FROM entregas LIMIT 1").fetchall()
        return conexao
    except Exception:
        conexao.close()
        raise


def ler_historico():
    conexao = abrir_historico()
    if conexao is None:
        return {}, []
    try:
        linhas = conexao.execute(
            "SELECT vaga_id, status FROM entregas"
        ).fetchall()
        estados = {int(linha["vaga_id"]): linha["status"] for linha in linhas}
        pendentes = [
            vaga_id for vaga_id, status in estados.items() if status != "enviado"
        ]
        return estados, pendentes
    finally:
        conexao.close()


def buscar_vagas(minimo):
    """Somente leitura: não coleta, analisa ou altera o MySQL."""
    conexao = conectar_banco()
    cursor = None
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """SELECT id, titulo, empresa, localizacao, url, score_ia,
                      recomendacao_ia, pontos_fortes_ia, gaps_ia,
                      justificativa_ia, data_analise_ia
               FROM vagas
               WHERE analisada_ia = TRUE
                 AND status_localizacao = 'elegivel'
                 AND score_ia >= %s
                 AND recomendacao_ia IN ('CANDIDATAR', 'AVALIAR')
                 AND data_analise_ia >= %s
               ORDER BY score_ia DESC, data_analise_ia DESC, id DESC""",
            (minimo, datetime.now() - timedelta(days=DIAS)),
        )
        return cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        conexao.close()


def selecionar_vagas(vagas, estados, limite):
    """O limite é aplicado depois de excluir as vagas já notificadas."""
    return [vaga for vaga in vagas if int(vaga["id"]) not in estados][:limite]


def limitar(texto, tamanho):
    texto = " ".join(str(texto or "").split())
    if len(texto) > tamanho:
        return texto[: tamanho - 1].rstrip() + "…"
    return texto


def lista_json(valor):
    if isinstance(valor, list):
        return [str(item) for item in valor if isinstance(item, str)]
    if not valor:
        return []
    try:
        import json
        dados = json.loads(valor)
        if isinstance(dados, list):
            return [item for item in dados if isinstance(item, str)]
    except (TypeError, ValueError):
        pass
    return []


def formatar_vaga(vaga):
    """Texto puro, sem parse_mode; nenhum dado da vaga vira instrução ao bot."""
    titulo = limitar(vaga.get("titulo"), 180) or "Cargo não informado"
    empresa = limitar(vaga.get("empresa"), 160) or "Não informada"
    local = limitar(vaga.get("localizacao"), 180) or "Não informada"
    recomendacao = vaga.get("recomendacao_ia") or "AVALIAR"
    score = int(vaga["score_ia"])

    linhas = [
        titulo,
        f"🏢 {empresa}",
        f"📍 {local}",
        "Modalidade e elegibilidade: confirme no anúncio.",
        f"🎯 Compatibilidade IA: {score}/100",
        f"Recomendação: {recomendacao}",
    ]
    fortes = lista_json(vaga.get("pontos_fortes_ia"))[:2]
    gaps = lista_json(vaga.get("gaps_ia"))[:2]
    if fortes:
        linhas.extend(["", "✅ Pontos fortes:"])
        linhas.extend("• " + limitar(item, 180) for item in fortes)
    if gaps:
        linhas.extend(["", "⚠️ Pontos a verificar:"])
        linhas.extend("• " + limitar(item, 180) for item in gaps)
    justificativa = limitar(vaga.get("justificativa_ia"), 700)
    if justificativa:
        linhas.extend(["", "📝 " + justificativa])

    url = str(vaga.get("url") or "").strip()
    try:
        partes = urlsplit(url)
        link_valido = (
            partes.scheme in ("http", "https")
            and bool(partes.netloc)
            and len(url) <= 1500
            and not any(caractere.isspace() for caractere in url)
        )
    except ValueError:
        link_valido = False
    if link_valido:
        linhas.extend(["", "🔗 Ver vaga:", url])
    else:
        linhas.extend(["", "Link indisponível; consulte a fonte da vaga."])

    texto = "\n".join(linhas)
    # O Hub acrescenta o cabeçalho antes de chamar sendMessage (limite 4096).
    if len(texto) > 3900:
        raise RuntimeError("A mensagem ficou longa demais. Revise os dados da vaga.")
    return texto


def preparar(conexao, vaga_id):
    conexao.execute(
        "INSERT INTO entregas (vaga_id, status, preparado_em) VALUES (?, ?, ?)",
        (vaga_id, "preparado", agora()),
    )
    conexao.commit()  # O registro existe ANTES da chamada externa.


def marcar_enviado(conexao, vaga_id):
    conexao.execute(
        "UPDATE entregas SET status = 'enviado', enviado_em = ? WHERE vaga_id = ?",
        (agora(), vaga_id),
    )
    conexao.commit()


def enviar_lote():
    with bloquear_envio():
        minimo, limite = configuracao()
        conexao = abrir_historico(criar=True)
        try:
            estados, pendentes = ler_historico()
            if pendentes:
                raise EnvioBloqueado(
                    "Há uma tentativa sem confirmação. Confira o Telegram e "
                    "não apague o histórico. IDs: " + ", ".join(map(str, pendentes))
                )
            vagas = selecionar_vagas(buscar_vagas(minimo), estados, limite)
            if not vagas:
                print("Nenhuma vaga nova para enviar.")
                return 0

            # Verifica a configuração antes de registrar uma tentativa de envio.
            verificar_hub()
            print(f"Vagas selecionadas: {len(vagas)}")
            for vaga in vagas:
                vaga_id = int(vaga["id"])
                texto = formatar_vaga(vaga)  # Valida antes de registrar a tentativa.
                preparar(conexao, vaga_id)
                try:
                    # A ponte usa somente o token armazenado no Hub.
                    enviar_notificacao(texto, origem="jobhunter")
                except Exception:
                    # Uma falha pode ocorrer DEPOIS de o Telegram aceitar o envio.
                    # Nunca reenviar automaticamente um resultado incerto.
                    conexao.execute(
                        "UPDATE entregas SET status = 'incerto' WHERE vaga_id = ?",
                        (vaga_id,),
                    )
                    conexao.commit()
                    raise EnvioBloqueado(
                        f"Envio da vaga {vaga_id} sem confirmação. Confira o Telegram "
                        "antes de resolver o histórico. Nenhuma repetição automática."
                    ) from None
                marcar_enviado(conexao, vaga_id)
                print(f"Vaga {vaga_id}: aceita pelo Telegram e registrada.")
            return 0
        finally:
            conexao.close()


def mostrar_status(preview=False):
    minimo, limite = configuracao()
    estados, pendentes = ler_historico()
    vagas = selecionar_vagas(buscar_vagas(minimo), estados, limite)
    print("\nJOBHUNTER AI — TELEGRAM")
    print(f"Filtro: score IA >= {minimo}; até {limite} vagas por envio.")
    print("Vagas já registradas como enviadas:", sum(
        status == "enviado" for status in estados.values()
    ))
    print("Vagas novas selecionadas:", len(vagas))
    if pendentes:
        print("ATENÇÃO: envio bloqueado por tentativa incerta. IDs:", pendentes)
    print("Nenhuma mensagem foi enviada.")
    if preview:
        for vaga in vagas:
            print("\n" + "=" * 45)
            print("ID da vaga:", vaga["id"])
            print("💼 JobHunter AI\n\n" + formatar_vaga(vaga))
        if not vagas:
            print("Não há vagas novas que atendam aos filtros.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--status", action="store_true")
    grupo.add_argument("--preview", action="store_true")
    grupo.add_argument("--send", action="store_true")
    grupo.add_argument("--run", action="store_true")
    args = parser.parse_args()
    try:
        if args.status or args.preview:
            mostrar_status(preview=args.preview)
            return 0
        if args.send:
            print("Será enviado um lote REAL de vagas pelo Telegram.")
            if input("Digite ENVIAR para confirmar: ").strip() != "ENVIAR":
                print("Envio cancelado.")
                return 0
        return enviar_lote()
    except (RuntimeError, sqlite3.Error, OSError, ValueError) as erro:
        # Não imprimir corpos de respostas, URLs com tokens ou credenciais.
        if isinstance(erro, RuntimeError):
            print("Erro:", erro, file=sys.stderr)
        else:
            print("Erro:", type(erro).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
