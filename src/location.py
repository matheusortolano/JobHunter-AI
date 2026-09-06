def analisar_localizacao(vaga):
    titulo = vaga.get("title", "").lower()
    localizacao = vaga.get("location", "").lower()
    descricao = vaga.get("description", "").lower()

    # Para saber ONDE a vaga realmente está,
    # confiamos principalmente no título e no campo location.
    texto_local = f"{titulo} {localizacao}"

    # A descrição é útil para descobrir se o remoto
    # aceita candidatos do Brasil / LATAM / mundo.
    texto_completo = f"{titulo} {localizacao} {descricao}"

    termos_remoto = [
        "remote",
        "remoto",
        "home office",
        "work from anywhere",
    ]

    termos_hibrido = [
        "hybrid",
        "híbrido",
        "hibrido",
    ]

    termos_sp = [
        "são paulo",
        "sao paulo",
        "sp, brazil",
        "sp, brasil",
        "sorocaba",
        "campinas",
        "jundiai",
        "jundiaí",
        "barueri",
        "alphaville",
    ]

    termos_brasil = [
        "brazil",
        "brasil",
        "latam",
        "latin america",
        "south america",
    ]

    termos_global = [
        "worldwide",
        "anywhere",
        "work from anywhere",
        "global remote",
    ]

    restricoes_exterior = [
        "remote de",
        "germany",
        "deutschland",
        "remote uk",
        "united kingdom",
        "uk only",
        "remote us",
        "us only",
        "united states only",
        "europe only",
        "eu only",
    ]

    eh_hibrida = any(
        termo in texto_local
        for termo in termos_hibrido
    )

    eh_remota = (
        vaga.get("remote", False)
        or any(termo in texto_local for termo in termos_remoto)
    )

    menciona_sp = any(
        termo in texto_local
        for termo in termos_sp
    )

    menciona_brasil = any(
        termo in texto_completo
        for termo in termos_brasil
    )

    menciona_global = any(
        termo in texto_completo
        for termo in termos_global
    )

    restrita_exterior = any(
        termo in texto_local
        for termo in restricoes_exterior
    )

    # -----------------------------
    # HÍBRIDO
    # -----------------------------

    if eh_hibrida:
        if menciona_sp:
            return "elegivel", "Híbrido em São Paulo"

        return "inelegivel", "Híbrido fora de São Paulo"

    # -----------------------------
    # REMOTO
    # -----------------------------

    if eh_remota:
        if restrita_exterior:
            return "inelegivel", "Remoto restrito a outro país/região"

        if menciona_brasil:
            return "elegivel", "Remoto disponível para Brasil/Latam"

        if menciona_global:
            return "elegivel", "Remoto global"

        return "incerto", "Remoto, mas região permitida não está clara"

    # -----------------------------
    # PRESENCIAL
    # -----------------------------

    if menciona_sp:
        return "elegivel", "Localização em São Paulo"

    if not localizacao:
        return "incerto", "Localização não informada"

    return "inelegivel", "Presencial fora de São Paulo"