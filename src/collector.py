import requests


ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
REMOTEOK_URL = "https://remoteok.com/api"


def buscar_vagas_arbeitnow():
    try:
        resposta = requests.get(ARBEITNOW_URL, timeout=10)
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
            headers={"User-Agent": "JobHunter-AI/1.0"},
            timeout=10,
        )

        resposta.raise_for_status()
        dados = resposta.json()

        vagas = []

        for vaga in dados:

            # O primeiro item da API contém informações legais,
            # não uma vaga.
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


def buscar_todas_vagas():
    vagas_arbeitnow = buscar_vagas_arbeitnow()
    vagas_remoteok = buscar_vagas_remoteok()

    return vagas_arbeitnow + vagas_remoteok