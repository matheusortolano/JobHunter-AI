def calcular_score(vaga):
    score = 0
    motivos = []

    titulo = vaga.get("title", "").lower()
    descricao = vaga.get("description", "").lower()

    # -----------------------------
    # SENIORIDADE
    # -----------------------------

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
        motivos.append("+ Senioridade compatível")

    if any(termo in titulo for termo in [
        "senior",
        "sr.",
        "lead",
        "staff",
        "principal",
    ]):
        score -= 35
        motivos.append("- Senioridade elevada")

    if any(termo in titulo for termo in [
        "manager",
        "director",
        "head",
    ]):
        score -= 30
        motivos.append("- Cargo de gestão")

    # -----------------------------
    # TÍTULO DA VAGA
    # -----------------------------

    if "python" in titulo:
        score += 25
        motivos.append("+ Python no título")

    if "backend" in titulo or "back-end" in titulo:
        score += 20
        motivos.append("+ Backend no título")

    if any(termo in titulo for termo in [
        "software engineer",
        "software developer",
        "developer",
    ]):
        score += 15
        motivos.append("+ Desenvolvimento de software no título")

    if any(termo in titulo for termo in [
        "data analyst",
        "business intelligence",
        "bi analyst",
    ]):
        score += 15
        motivos.append("+ Dados/BI no título")

    if any(termo in titulo for termo in [
        "automation",
        "automação",
    ]):
        score += 15
        motivos.append("+ Automação no título")

    # -----------------------------
    # DESCRIÇÃO
    # -----------------------------

    if "python" in descricao:
        score += 10
        motivos.append("+ Python na descrição")

    if "sql" in descricao or "mysql" in descricao:
        score += 8
        motivos.append("+ SQL/MySQL na descrição")

    if "api" in descricao:
        score += 8
        motivos.append("+ APIs na descrição")

    if "fastapi" in descricao:
        score += 10
        motivos.append("+ FastAPI na descrição")

    if "power bi" in descricao:
        score += 8
        motivos.append("+ Power BI na descrição")

    if "sap" in descricao:
        score += 8
        motivos.append("+ SAP na descrição")

    if "oracle" in descricao:
        score += 8
        motivos.append("+ Oracle na descrição")

    if "erp" in descricao:
        score += 5
        motivos.append("+ ERP na descrição")

    # -----------------------------
    # REMOTO
    # -----------------------------

    if vaga.get("remote"):
        score += 10
        motivos.append("+ Vaga remota")
    else:
        motivos.append("- Vaga não remota")

    # Limita o score entre 0 e 100
    score = max(0, min(score, 100))

    return score, motivos