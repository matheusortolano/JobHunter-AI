import re


TERMOS_INTERESSE = [
    # Desenvolvimento
    "python",
    "backend",
    "back-end",
    "developer",
    "software engineer",
    "software developer",

    # Dados / BI
    "data analyst",
    "data engineer",
    "business intelligence",
    "bi analyst",
    "power bi",
    "analytics",

    # Automação
    "automation",
    "automação",

    # ERP / sistemas
    "sap",
    "oracle",
    "erp",

    # QA
    "quality assurance",
    "qa engineer",
    "qa analyst",
    "software tester",

    # Sistemas
    "systems analyst",
    "system analyst",
    "analista de sistemas",
]


def contem_termo(texto, termo):
    padrao = rf"\b{re.escape(termo)}\b"
    return re.search(padrao, texto, re.IGNORECASE) is not None


def filtrar_vagas(vagas):
    vagas_filtradas = []

    for vaga in vagas:
        titulo = vaga.get("title", "")

        if any(
            contem_termo(titulo, termo)
            for termo in TERMOS_INTERESSE
        ):
            vagas_filtradas.append(vaga)

    return vagas_filtradas