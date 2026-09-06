def calcular_score(vaga):
    score = 0

    titulo = vaga.get("title", "").lower()
    descricao = vaga.get("description", "").lower()

    texto = titulo + " " + descricao

    # Senioridade desejada
    if any(termo in texto for termo in ["junior", "jr", "estágio", "estagio", "intern", "internship", "trainee"]):
        score += 25

    # Tecnologias / áreas de interesse
    if "python" in texto:
        score += 20

    if "backend" in texto or "back-end" in texto:
        score += 15

    if "api" in texto:
        score += 10

    if "sql" in texto or "mysql" in texto:
        score += 10

    if "automation" in texto or "automação" in texto:
        score += 10

    if any(termo in texto for termo in ["business intelligence", "power bi", "data analyst"]):
        score += 10

    if any(termo in texto for termo in ["sap", "oracle", "erp"]):
        score += 10

    # Trabalho remoto
    if vaga.get("remote"):
        score += 10

    # Penalizações
    if any(termo in titulo for termo in ["senior", "sr.", "lead", "staff", "principal"]):
        score -= 30

    if any(termo in titulo for termo in ["manager", "director", "head"]):
        score -= 25

    # Mantém entre 0 e 100
    return max(0, min(score, 100))