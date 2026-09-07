import argparse
import json
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv


RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

# Os dois projetos ficam dentro de D:\Projetos\Python.
HUB_ROOT = Path(
    os.getenv(
        "MATHEUS_HUB_ROOT",
        str(RAIZ.parent / "Matheus-AI-Hub"),
    )
).resolve()

HUB_PYTHON = HUB_ROOT / ".venv" / "Scripts" / "python.exe"
HUB_CLI = HUB_ROOT / "src" / "hub_cli.py"


def chamar_hub(argumentos, payload=None):
    if not HUB_PYTHON.is_file():
        raise RuntimeError(
            "Python do Hub não encontrado. Confira o caminho do projeto."
        )

    if not HUB_CLI.is_file():
        raise RuntimeError(
            "hub_cli.py não encontrado no Matheus AI Hub."
        )

    comando = [
        str(HUB_PYTHON),
        str(HUB_CLI),
        *argumentos,
    ]

    try:
        processo = subprocess.run(
            comando,
            cwd=HUB_ROOT,
            input=(
                json.dumps(payload, ensure_ascii=False)
                if payload is not None
                else None
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )

    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "O Hub demorou para responder. Se houve envio, "
            "confira o Telegram antes de tentar novamente."
        ) from None

    except OSError:
        raise RuntimeError(
            "Não foi possível iniciar o processo do Hub."
        ) from None

    if processo.returncode != 0:
        raise RuntimeError(
            "O Hub não concluiu a operação. "
            "Confira o terminal do Hub e suas configurações."
        )

    return processo.stdout.strip()


def verificar_hub():
    return chamar_hub(["--check"])


def enviar_notificacao(texto, origem="jobhunter"):
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("A mensagem não pode estar vazia.")

    return chamar_hub(
        ["--stdin"],
        {
            "source": origem,
            "text": texto.strip(),
        },
    )


def main():
    parser = argparse.ArgumentParser(
        description="Ponte JobHunter → Matheus AI Hub."
    )

    grupo = parser.add_mutually_exclusive_group(required=True)

    grupo.add_argument(
        "--check",
        action="store_true",
        help="Verifica a conexão com o Hub sem enviar mensagens.",
    )

    grupo.add_argument(
        "--test",
        action="store_true",
        help="Envia uma mensagem de teste após confirmação.",
    )

    args = parser.parse_args()

    try:
        if args.check:
            print(verificar_hub())
            return 0

        print("Será enviada uma mensagem de teste ao Telegram.")

        if input("Digite ENVIAR para confirmar: ").strip() != "ENVIAR":
            print("Teste cancelado.")
            return 0

        resultado = enviar_notificacao(
            "Ponte com o JobHunter funcionando!\n\n"
            "As próximas notificações poderão trazer vagas "
            "analisadas, scores e links para candidatura."
        )

        print(resultado)
        return 0

    except (RuntimeError, ValueError) as erro:
        print("Erro:", erro)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())