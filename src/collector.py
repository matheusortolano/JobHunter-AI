import os

import requests
from dotenv import load_dotenv


load_dotenv()


ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
REMOTEOK_URL = "https://remoteok.com/api"
ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/br/search/1"


def buscar_vagas_arbeitnow():
    try:
        resposta = requests.get(
            ARBEITNOW_URL,
            timeout=10
        )

        resposta.raise_for_status()
        dados = resposta.json()

        vagas = []

        for vaga in dados.get("data", []):
            vagas.append({
                "title": vaga.get("title", ""),
                "company_name": vaga.get("company_name", ""),
                "location": vaga.get("location", ""),
                "remote": vaga.get("remote", False),
                "description": vaga.get("description", ""),
                "url": vaga.get("url", ""),
                "source": "Arbeitnow",
            })

        return vagas

    except requests.RequestException as erro:
        print("Erro ao buscar vagas da Arbeitnow:", erro)
        return []


def buscar_vagas_remoteok():
    try:
        resposta = requests.get(
            REMOTEOK_URL,
            headers={
                "User-Agent": "JobHunter-AI/1.0"
            },
            timeout=10,
        )

        resposta.raise_for_status()
        dados = resposta.json()

        vagas = []

        for vaga in dados:

            if not vaga.get("position"):
                continue

            descricao = vaga.get("description") or ""
            localizacao = vaga.get("location") or ""
            tags = vaga.get("tags") or []

            texto_remoto = (
                vaga.get("position", "")
                + " "
                + localizacao
                + " "
                + " ".join(tags)
                + " "
                + descricao
            ).lower()

            remoto = any(
                termo in texto_remoto
                for termo in [
                    "remote",
                    "work from anywhere",
                    "home office",
                ]
            )

            vagas.append({
                "title": vaga.get("position", ""),
                "company_name": vaga.get("company", ""),
                "location": localizacao,
                "remote": remoto,
                "description": descricao,
                "url": vaga.get("url", ""),
                "source": "Remote OK",
            })

        return vagas

    except requests.RequestException as erro:
        print("Erro ao buscar vagas da Remote OK:", erro)
        return []


def buscar_vagas_adzuna():
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")

    if not app_id or not app_key:
        print("Erro: credenciais da Adzuna não encontradas no .env")
        return []

    parametros = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": 50,
        "what": "python",
        "where": "São Paulo",
        "content-type": "application/json",
    }

    try:
        resposta = requests.get(
            ADZUNA_URL,
            params=parametros,
            timeout=10,
        )

        resposta.raise_for_status()
        dados = resposta.json()

        vagas = []

        for vaga in dados.get("results", []):
            titulo = vaga.get("title", "")
            descricao = vaga.get("description", "")

            localizacao = (
                vaga.get("location", {})
                .get("display_name", "")
            )

            empresa = (
                vaga.get("company", {})
                .get("display_name", "")
            )

            texto_remoto = (
                titulo
                + " "
                + descricao
                + " "
                + localizacao
            ).lower()

            remoto = any(
                termo in texto_remoto
                for termo in [
                    "remote",
                    "remoto",
                    "home office",
                ]
            )

            vagas.append({
                "title": titulo,
                "company_name": empresa,
                "location": localizacao,
                "remote": remoto,
                "description": descricao,
                "url": vaga.get("redirect_url", ""),
                "source": "Adzuna",
            })

        return vagas

    except requests.RequestException as erro:
        print("Erro ao buscar vagas da Adzuna:", erro)
        return []


def buscar_todas_vagas():
    vagas_arbeitnow = buscar_vagas_arbeitnow()
    vagas_remoteok = buscar_vagas_remoteok()
    vagas_adzuna = buscar_vagas_adzuna()

    print(f"Arbeitnow: {len(vagas_arbeitnow)} vagas")
    print(f"Remote OK: {len(vagas_remoteok)} vagas")
    print(f"Adzuna Brasil: {len(vagas_adzuna)} vagas")

    return (
        vagas_arbeitnow
        + vagas_remoteok
        + vagas_adzuna
    )