import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors


load_dotenv()


ANALISE_SCHEMA = {
    "type": "object",
    "properties": {
        "score_ia": {
            "type": "integer"
        },
        "recomendacao": {
            "type": "string",
            "enum": [
                "CANDIDATAR",
                "AVALIAR",
                "DESCARTAR",
            ],
        },
        "pontos_fortes": {
            "type": "array",
            "items": {
                "type": "string"
            },
        },
        "gaps": {
            "type": "array",
            "items": {
                "type": "string"
            },
        },
        "justificativa": {
            "type": "string"
        },
    },
    "required": [
        "score_ia",
        "recomendacao",
        "pontos_fortes",
        "gaps",
        "justificativa",
    ],
}


def carregar_perfil():
    raiz_projeto = Path(__file__).resolve().parent.parent
    caminho_perfil = raiz_projeto / "data" / "profile.json"

    with open(
        caminho_perfil,
        "r",
        encoding="utf-8",
    ) as arquivo:
        return json.load(arquivo)


def analisar_vaga(vaga):
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY não encontrada no .env"
        )

    perfil = carregar_perfil()

    client = genai.Client(
        api_key=api_key
    )

    prompt = f"""
Você é um recrutador técnico analisando a compatibilidade
entre um candidato em transição para tecnologia e uma vaga.

Analise de forma realista e criteriosa.

Não aumente a pontuação apenas porque uma tecnologia aparece
na descrição.

Considere especialmente:
- senioridade exigida;
- experiência profissional exigida;
- tecnologias obrigatórias;
- tecnologias desejáveis;
- formação;
- possibilidade real de candidatura;
- experiência corporativa transferível.

PERFIL DO CANDIDATO:
{json.dumps(perfil, ensure_ascii=False)}

VAGA:

Cargo:
{vaga.get("title", "")}

Empresa:
{vaga.get("company_name", "")}

Localização:
{vaga.get("location", "")}

Descrição:
{vaga.get("description", "")}

Score calculado pelo algoritmo:
{vaga.get("score", 0)}/100
"""

    modelos = [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
    ]

    ultimo_erro = None

    for modelo in modelos:
        for tentativa in range(3):
            try:
                resposta = client.models.generate_content(
                    model=modelo,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_json_schema": ANALISE_SCHEMA,
                    },
                )

                return json.loads(resposta.text)

            except errors.ServerError as erro:
                ultimo_erro = erro

                status = (
                    getattr(erro, "code", None)
                    or getattr(erro, "status_code", None)
                )

                if status == 503:
                    espera = 2 ** tentativa

                    print(
                        f"{modelo} indisponível. "
                        f"Nova tentativa em {espera}s..."
                    )

                    time.sleep(espera)
                    continue

                raise

        print(
            f"{modelo} continua indisponível. "
            "Tentando modelo alternativo..."
        )

    raise RuntimeError(
        "Gemini indisponível após todas as tentativas."
    ) from ultimo_erro