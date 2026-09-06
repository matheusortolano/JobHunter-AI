TERMOS_INTERESSE = [
    "python",
    "backend",
    "back-end",
    "developer",
    "software",
    "data",
    "business intelligence",
    "bi ",
    "automation",
    "sap",
    "oracle",
    "erp",
    "qa",
    "quality assurance",
    "junior",
    "jr",
    "estágio",
    "estagio",
    "intern",
    "internship",
    "trainee",
]


def filtrar_vagas(vagas):
    vagas_filtradas = []

    for vaga in vagas:
        titulo = vaga.get("title", "").lower()

        for termo in TERMOS_INTERESSE:
            if termo in titulo:
                vagas_filtradas.append(vaga)
                break

    return vagas_filtradas