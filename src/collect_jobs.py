"""Executor seguro da coleta do JobHunter AI.

Uso:
    python src/collect_jobs.py --status
    python src/collect_jobs.py --run

Este arquivo não chama o Gemini e não altera o esquema do banco.
A coleta e os upserts continuam sendo responsabilidade de main.py.
"""

import argparse
import errno
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MAIN = RAIZ / "src" / "main.py"
DADOS = RAIZ / "data"
LOG = DADOS / "logs" / "collector.log"
ESTADO = DADOS / "collector_state.json"
TRAVA = DADOS / ".collector.lock"
TIMEOUT_SEGUNDOS = 1800


class ColetaEmExecucao(Exception):
    pass


@contextmanager
def bloquear_coleta():
    """Trava exclusiva liberada pelo sistema ao terminar o processo."""
    DADOS.mkdir(parents=True, exist_ok=True)

    # Não apague este arquivo: a trava é associada ao arquivo aberto.
    with open(TRAVA, "a+b") as arquivo:
        arquivo.seek(0)
        descritor = arquivo.fileno()

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
                raise ColetaEmExecucao(
                    "Outra coleta já está em execução. Nenhuma nova coleta foi iniciada."
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


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def salvar_estado(estado):
    DADOS.mkdir(parents=True, exist_ok=True)
    temporario = ESTADO.with_suffix(".json.tmp")

    with open(temporario, "w", encoding="utf-8") as arquivo:
        json.dump(estado, arquivo, ensure_ascii=False, indent=2)
        arquivo.flush()
        os.fsync(arquivo.fileno())

    os.replace(temporario, ESTADO)


def carregar_estado():
    if not ESTADO.exists():
        return None

    try:
        with open(ESTADO, "r", encoding="utf-8") as arquivo:
            estado = json.load(arquivo)

        if not isinstance(estado, dict):
            raise ValueError("Formato inválido.")

        return estado
    except (OSError, ValueError, TypeError):
        raise RuntimeError(
            "O histórico da coleta está inválido. "
            "Não apague o arquivo para esconder uma falha."
        ) from None


def obter_segredos():
    """Usa os valores locais apenas para ocultá-los dos logs."""
    segredos = []

    try:
        from dotenv import dotenv_values
        valores = dict(dotenv_values(RAIZ / ".env"))
    except ImportError:
        valores = {}

    valores.update(os.environ)

    for nome, valor in valores.items():
        nome = nome.upper()
        if (
            isinstance(valor, str)
            and len(valor) >= 6
            and any(
                termo in nome
                for termo in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
            )
        ):
            segredos.append(valor)

    return sorted(set(segredos), key=len, reverse=True)


def proteger_log(texto, segredos):
    for segredo in segredos:
        texto = texto.replace(segredo, "[SEGREDO_OCULTO]")

    # Proteção adicional para parâmetros de credenciais em URLs.
    return re.sub(
        r"(?i)([?&](?:api[_-]?key|app[_-]?key|access[_-]?token|password|secret)=)[^&\s]+",
        r"\1[SEGREDO_OCULTO]",
        texto,
    )


def registrar(mensagem):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as arquivo:
        arquivo.write(mensagem.rstrip() + "\n")


def mostrar_status():
    estado = carregar_estado()

    print("\nJOBHUNTER AI — COLETA")
    if estado is None:
        print("Nenhuma execução registrada por este executor.")
    else:
        print("Início:", estado.get("inicio", "-"))
        print("Fim:", estado.get("fim", "-"))
        print("Resultado:", estado.get("resultado", "-"))
        print("Código de saída:", estado.get("codigo_saida", "-"))

    print("Log:", LOG)
    print("Este comando não chama APIs nem altera o MySQL.")


def executar_coleta():
    with bloquear_coleta():
        if not MAIN.is_file():
            raise RuntimeError("src/main.py não encontrado.")

        segredos = obter_segredos()
        estado = {
            "inicio": agora(),
            "fim": None,
            "resultado": "em_andamento",
            "codigo_saida": None,
        }
        salvar_estado(estado)

        print("\nJOBHUNTER AI — COLETA")
        print("Executando main.py com o Python do ambiente atual...")
        print("O Gemini não será chamado por este executor.")

        registrar(f"\n===== Início: {estado['inicio']} =====")

        codigo = 1
        resultado = "erro"

        try:
            ambiente = os.environ.copy()
            ambiente["PYTHONUNBUFFERED"] = "1"

            processo = subprocess.run(
                [sys.executable, "-u", str(MAIN)],
                cwd=RAIZ,
                env=ambiente,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SEGUNDOS,
                check=False,
            )

            saida = proteger_log(processo.stdout or "", segredos)
            if saida:
                registrar(saida)

            codigo = processo.returncode
            resultado = "concluida" if codigo == 0 else "erro"

        except subprocess.TimeoutExpired as erro:
            codigo = 124
            resultado = "tempo_esgotado"
            saida = erro.stdout or b""
            if isinstance(saida, bytes):
                saida = saida.decode("utf-8", errors="replace")
            if saida:
                registrar(proteger_log(saida, segredos))
            registrar("Tempo máximo de 30 minutos atingido.")

        except OSError as erro:
            codigo = 1
            resultado = "erro"
            registrar(
                proteger_log(
                    f"Falha ao iniciar o processo: {type(erro).__name__}.",
                    segredos,
                )
            )

        finally:
            estado["fim"] = agora()
            estado["resultado"] = resultado
            estado["codigo_saida"] = codigo
            salvar_estado(estado)
            registrar(
                f"===== Fim: {estado['fim']} | "
                f"Resultado: {resultado} | Código: {codigo} ====="
            )

        print("Resultado:", resultado)
        print("Código de saída:", codigo)
        print("Log:", LOG)
        return codigo


def main():
    parser = argparse.ArgumentParser(
        description="Executor da coleta do JobHunter AI."
    )
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--run", action="store_true", help="Executa a coleta.")
    grupo.add_argument("--status", action="store_true", help="Consulta o histórico.")
    args = parser.parse_args()

    try:
        if args.run:
            return executar_coleta()
        mostrar_status()
        return 0
    except (ColetaEmExecucao, RuntimeError, OSError) as erro:
        print("Coleta não iniciada:", erro)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
