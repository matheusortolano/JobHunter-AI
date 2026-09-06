import requests


URL = "https://www.arbeitnow.com/api/job-board-api"


def buscar_vagas():
    resposta = requests.get(URL, timeout=10)

    if resposta.status_code == 200:
        dados = resposta.json()
        return dados["data"]

    print("Erro ao buscar vagas:", resposta.status_code)
    return []