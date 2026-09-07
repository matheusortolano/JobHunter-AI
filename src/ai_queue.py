import argparse
import errno
import json
import os
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path

from dotenv import load_dotenv

from ai_analyzer import AnalisePendente, analisar_vaga
from database import buscar_melhor_vaga, conectar_banco, salvar_analise_ia


RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

ARQUIVO_ESTADO = RAIZ / "data" / "ai_queue_state.json"
ARQUIVO_TRAVA = RAIZ / "data" / ".ai_queue.lock"
LIMITE_POR_EXECUCAO = 1


class FilaEmExecucao(Exception):
    """Outra execução já está usando a fila."""


@contextmanager
def bloquear_fila():
    """Trava do sistema operacional, liberada inclusive após um crash."""
    ARQUIVO_TRAVA.parent.mkdir(parents=True, exist_ok=True)

    # O arquivo é permanente: apagá-lo poderia permitir duas travas distintas.
    with open(ARQUIVO_TRAVA, "a+b") as arquivo:
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
                raise FilaEmExecucao(
                    "Outra execução já está usando a fila. Nenhuma chamada foi feita."
                ) from None
            raise

        try:
            yield
        finally:
            if os.name == "nt":
                arquivo.seek(0)
                msvcrt.locking(descritor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descritor, fcntl.LOCK_UN)


def obter_limite_diario():
    try:
        valor = int(os.getenv("AI_DAILY_LIMIT", "3"))
    except ValueError:
        raise ValueError("AI_DAILY_LIMIT deve ser um número inteiro.") from None

    if valor < 1:
        raise ValueError("AI_DAILY_LIMIT deve ser maior que zero.")
    return valor


def novo_estado(hoje):
    return {
        "data": hoje,
        "tentativas": 0,
        "pausa_ate": None,
        "motivo_pausa": None,
    }


def carregar_estado():
    agora = datetime.now().astimezone()
    hoje = agora.date()

    if not ARQUIVO_ESTADO.exists():
        return novo_estado(hoje.isoformat())

    try:
        with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as arquivo:
            estado = json.load(arquivo)

        if not isinstance(estado, dict):
            raise ValueError

        data_texto = estado.get("data")
        tentativas = estado.get("tentativas")
        if not isinstance(data_texto, str):
            raise ValueError
        if type(tentativas) is not int or tentativas < 0:
            raise ValueError

        data_estado = date.fromisoformat(data_texto)
        if data_estado > hoje:
            raise RuntimeError(
                "A data do controle está no futuro. Confira o relógio do computador."
            )

        pausa_texto = estado.get("pausa_ate")
        motivo = estado.get("motivo_pausa")
        if pausa_texto is not None:
            if not isinstance(pausa_texto, str):
                raise ValueError
            pausa = datetime.fromisoformat(pausa_texto)
            if pausa.tzinfo is None or pausa.utcoffset() is None:
                raise ValueError
        else:
            pausa = None

        if motivo is not None and not isinstance(motivo, str):
            raise ValueError

    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise RuntimeError(
            "O controle da fila está inválido. Nenhuma análise será executada. "
            "Não apague o arquivo para zerar o contador."
        ) from None

    # A virada do dia zera as tentativas, mas não apaga uma pausa futura.
    if data_estado < hoje:
        estado["data"] = hoje.isoformat()
        estado["tentativas"] = 0

    if pausa is not None and agora >= pausa:
        estado["pausa_ate"] = None
        estado["motivo_pausa"] = None

    estado.setdefault("pausa_ate", None)
    estado.setdefault("motivo_pausa", None)
    return estado


def salvar_estado(estado):
    ARQUIVO_ESTADO.parent.mkdir(parents=True, exist_ok=True)
    temporario = ARQUIVO_ESTADO.with_suffix(".json.tmp")

    # A troca atômica evita deixar um JSON pela metade após uma interrupção.
    with open(temporario, "w", encoding="utf-8") as arquivo:
        json.dump(estado, arquivo, indent=2, ensure_ascii=False)
        arquivo.flush()
        os.fsync(arquivo.fileno())

    os.replace(temporario, ARQUIVO_ESTADO)


def confirmar_analise_salva(vaga_id):
    conexao = conectar_banco()
    cursor = None
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT analisada_ia FROM vagas WHERE id = %s",
            (vaga_id,),
        )
        resultado = cursor.fetchone()
        return bool(resultado and resultado[0])
    finally:
        if cursor is not None:
            cursor.close()
        conexao.close()


def pausar_ate_amanha(estado):
    # Pausa conservadora: não afirma conhecer o reset real da cota do Google.
    amanha = date.today() + timedelta(days=1)
    proxima_meia_noite = datetime.combine(amanha, time.min).astimezone()
    estado["pausa_ate"] = proxima_meia_noite.isoformat()
    estado["motivo_pausa"] = "Cota atingida ou serviço temporariamente indisponível."
    salvar_estado(estado)
    return estado["pausa_ate"]


def executar_fila():
    with bloquear_fila():
        limite = obter_limite_diario()
        estado = carregar_estado()

        print("\nJOBHUNTER AI — FILA DE ANÁLISES")
        print(f"Tentativas hoje: {estado['tentativas']}/{limite}")

        if estado["pausa_ate"]:
            print("Fila pausada:", estado["motivo_pausa"])
            print("Próxima tentativa permitida:", estado["pausa_ate"])
            print("Nenhuma chamada será feita.")
            return

        restantes = limite - estado["tentativas"]
        if restantes <= 0:
            print("Limite diário atingido. Nenhuma chamada será feita.")
            return

        for _ in range(min(LIMITE_POR_EXECUCAO, restantes)):
            vaga = buscar_melhor_vaga()
            if not vaga:
                print("Nenhuma vaga relevante pendente de análise.")
                return

            print(f"\nVaga: {vaga['title']}")
            print(f"Score do algoritmo: {vaga['score']}/100")

            # Reservar antes da chamada impede que uma falha zere a tentativa.
            estado["tentativas"] += 1
            salvar_estado(estado)

            try:
                resultado = analisar_vaga(vaga)
                salvar_analise_ia(vaga["id"], resultado)

                if not confirmar_analise_salva(vaga["id"]):
                    print("Não foi possível confirmar o salvamento. Fila interrompida.")
                    return

                print("\nAnálise concluída!")
                print(f"Score IA: {resultado['score_ia']}/100")
                print("Recomendação:", resultado["recomendacao"])

            except AnalisePendente as erro:
                print("\nAnálise adiada:", erro)
                print("A vaga permanece pendente no MySQL.")
                print("Fila pausada até:", pausar_ate_amanha(estado))
                return

            except Exception as erro:
                print(f"\nFalha: {type(erro).__name__}. Fila interrompida.")
                print("Confira a configuração antes de executar novamente.")
                return

        print("\nExecução finalizada.")


def mostrar_status():
    limite = obter_limite_diario()
    estado = carregar_estado()
    print("\nJOBHUNTER AI — STATUS")
    print("Data:", estado["data"])
    print(f"Tentativas: {estado['tentativas']}/{limite}")
    print("Restantes:", max(0, limite - estado["tentativas"]))
    if estado["pausa_ate"]:
        print("Pausada até:", estado["pausa_ate"])
        print("Motivo:", estado["motivo_pausa"])
    else:
        print("Pausa: nenhuma")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fila controlada de análises do JobHunter."
    )
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--run", action="store_true", help="Executa uma análise.")
    grupo.add_argument("--status", action="store_true", help="Mostra o contador.")
    args = parser.parse_args()

    try:
        if args.run:
            executar_fila()
        else:
            mostrar_status()
    except (FilaEmExecucao, RuntimeError, ValueError, OSError) as erro:
        print("Fila não iniciada:", erro)
        raise SystemExit(1) from None
