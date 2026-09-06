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

    # Análise de sistemas
    "systems analyst",
    "system analyst",
    "analista de sistemas",
]


def filtrar_vagas(vagas):
    vagas_filtradas = []

    for vaga in vagas:
        titulo = vaga.get("title", "").lower()

        if any(termo in titulo for termo in TERMOS_INTERESSE):
            vagas_filtradas.append(vaga)

    return vagas_filtradas