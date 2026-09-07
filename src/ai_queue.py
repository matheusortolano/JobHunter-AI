import argparse
import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from ai_analyzer import AnalisePendente, analisar_vaga
from database import (
    buscar_melhor_vaga,
    conectar_banco,
    salvar_analise_ia,
)


RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

ARQUIVO_ESTADO = RAIZ / "data" / "ai_queue_state.json"
LIMITE_POR_EXECUCAO = 1


def obter_limite_diario():
    valor = int(os.getenv("AI_DAILY_LIMIT", "3"))

    if valor < 1:
        raise ValueError("AI_DAILY_LIMIT deve ser maior que zero.")

    return valor


def carregar_estado():
    hoje = date.today().isoformat()

    if not ARQUIVO_ESTADO.exists():
        return {
            "data": hoje,
            "tentativas": 0,
        }

    try:
        with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as arquivo:
            estado = json.load(arquivo)

        if not isinstance(estado, dict):
            raise ValueError

        if not isinstance(estado.get("data"), str):
            raise ValueError

        tentativas = estado.get("tentativas")

        if type(tentativas) is not int or tentativas < 0:
            raise ValueError

        data_estado = date.fromisoformat(estado["data"])

    except (OSError, ValueError, json.JSONDecodeError):
        raise RuntimeError(
            "O arquivo de controle da fila está inválido. "
            "Nenhuma análise será executada."
        ) from None

    if data_estado > date.today():
        raise RuntimeError(
            "A data do controle está no futuro. "
            "Confira o relógio do computador."
        )

    if estado["data"] != hoje:
        return {
            "data": hoje,
            "tentativas": 0,
        }

    return estado


def salvar_estado(estado):
    ARQUIVO_ESTADO.parent.mkdir(parents=True, exist_ok=True)

    temporario = ARQUIVO_ESTADO.with_suffix(".json.tmp")

    with open(temporario, "w", encoding="utf-8") as arquivo:
        json.dump(estado, arquivo, indent=2, ensure_ascii=False)

    os.replace(temporario, ARQUIVO_ESTADO)


def confirmar_analise_salva(vaga_id):
    conexao = conectar_banco()
    cursor = conexao.cursor()

    try:
        cursor.execute(
            """
            SELECT analisada_ia
            FROM vagas
            WHERE id = %s
            """,
            (vaga_id,),
        )

        resultado = cursor.fetchone()

        return bool(resultado and resultado[0])

    finally:
        cursor.close()
        conexao.close()


def executar_fila():
    limite = obter_limite_diario()
    estado = carregar_estado()

    restantes = limite - estado["tentativas"]

    print("\nJOBHUNTER AI — FILA DE ANÁLISES")
    print(f"Tentativas hoje: {estado['tentativas']}/{limite}")

    if restantes <= 0:
        print("Limite diário atingido. Nenhuma chamada será feita.")
        return

    quantidade = min(LIMITE_POR_EXECUCAO, restantes)

    for _ in range(quantidade):
        vaga = buscar_melhor_vaga()

        if not vaga:
            print("Nenhuma vaga relevante pendente de análise.")
            return

        print(f"\nVaga: {vaga['title']}")
        print(f"Score do algoritmo: {vaga['score']}/100")

        # Reservamos a tentativa ANTES de chamar a IA.
        # Assim, uma falha também consome o limite do aplicativo.
        estado["tentativas"] += 1
        salvar_estado(estado)

        try:
            resultado = analisar_vaga(vaga)

            salvar_analise_ia(
                vaga["id"],
                resultado,
            )

            if not confirmar_analise_salva(vaga["id"]):
                print(
                    "Não foi possível confirmar o salvamento. "
                    "A fila será interrompida."
                )
                return

            print("\nAnálise concluída!")
            print(f"Score IA: {resultado['score_ia']}/100")
            print("Recomendação:", resultado["recomendacao"])

        except AnalisePendente as erro:
            print("\nAnálise adiada:")
            print(erro)
            print("A vaga permanece pendente no MySQL.")
            return

        except Exception as erro:
            print(
                f"\nFalha: {type(erro).__name__}. "
                "A fila foi interrompida."
            )
            print(
                "Confira o erro com o teste manual antes "
                "de executar novamente."
            )
            return

    print("\nExecução finalizada.")


def mostrar_status():
    limite = obter_limite_diario()
    estado = carregar_estado()

    print("\nJOBHUNTER AI — STATUS")
    print("Data:", estado["data"])
    print(f"Tentativas: {estado['tentativas']}/{limite}")
    print(
        "Restantes:",
        max(0, limite - estado["tentativas"]),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fila controlada de análises do JobHunter."
    )

    parser.add_argument(
        "--run",
        action="store_true",
        help="Executa uma análise, respeitando o limite diário.",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Mostra o contador sem chamar a IA.",
    )

    args = parser.parse_args()

    if args.run:
        executar_fila()

    else:
        mostrar_status()