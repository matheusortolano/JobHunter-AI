def calcular_score(vaga):
    score = 0

    titulo = vaga.get("title", "").lower()
    descricao = vaga.get("description", "").lower()

    # --------------------------------
    # SENIORIDADE
    # --------------------------------

    if any(termo in titulo for termo in [
        "junior",
        "jr",
        "associate",
        "estágio",
        "estagio",
        "intern",
        "internship",
        "trainee",
    ]):
        score += 30

    if any(termo in titulo for termo in [
        "senior",
        "sr.",
        "lead",
        "staff",
        "principal",
    ]):
        score -= 35

    if any(termo in titulo for termo in [
        "manager",
        "director",
        "head",
    ]):
        score -= 30

    # --------------------------------
    # TÍTULO DA VAGA
    # --------------------------------

    if "python" in titulo:
        score += 25

    if "backend" in titulo or "back-end" in titulo:
        score += 20

    if any(termo in titulo for termo in [
        "software engineer",
        "software developer",
        "developer",
    ]):
        score += 15

    if any(termo in titulo for termo in [
        "data analyst",
        "business intelligence",
        "bi analyst",
    ]):
        score += 15

    if any(termo in titulo for termo in [
        "automation",
        "automação",
    ]):
        score += 15

    # --------------------------------
    # TECNOLOGIAS NA DESCRIÇÃO
    # --------------------------------

    if "python" in descricao:
        score += 10

    if "sql" in descricao or "mysql" in descricao:
        score += 8

    if "api" in descricao:
        score += 8

    if "fastapi" in descricao:
        score += 10

    if "power bi" in descricao:
        score += 8

    if "sap" in descricao:
        score += 8

    if "oracle" in descricao:
        score += 8

    if "erp" in descricao:
        score += 5

    # --------------------------------
    # REMOTO
    # --------------------------------

    if vaga.get("remote"):
        score += 10

    return max(0, min(score, 100))