from collector import buscar_todas_vagas
from filters import filtrar_vagas
from scorer import calcular_score
from location import analisar_localizacao
from deduplicator import deduplicar_vagas
from database import salvar_vagas

SCORE_MINIMO = 40


vagas_coletadas = buscar_todas_vagas()

vagas = deduplicar_vagas(vagas_coletadas)

vagas_filtradas = filtrar_vagas(vagas)

for vaga in vagas_filtradas:
    vaga["score"], vaga["motivos"] = calcular_score(vaga)

    status_localizacao, motivo_localizacao = analisar_localizacao(vaga)

    vaga["status_localizacao"] = status_localizacao
    vaga["motivo_localizacao"] = motivo_localizacao

vagas_novas, atualizadas = salvar_vagas(vagas_filtradas)

# Elegíveis e relevantes
vagas_elegiveis = [
    vaga
    for vaga in vagas_filtradas
    if vaga["status_localizacao"] == "elegivel"
    and vaga["score"] >= SCORE_MINIMO
]


# Elegíveis geograficamente, mas pouco compatíveis
vagas_score_baixo = [
    vaga
    for vaga in vagas_filtradas
    if vaga["status_localizacao"] == "elegivel"
    and vaga["score"] < SCORE_MINIMO
]


# Localização ainda não conclusiva
vagas_incertas = [
    vaga
    for vaga in vagas_filtradas
    if vaga["status_localizacao"] == "incerto"
]


# Geograficamente inviáveis
vagas_inelegiveis = [
    vaga
    for vaga in vagas_filtradas
    if vaga["status_localizacao"] == "inelegivel"
]


vagas_ordenadas = sorted(
    vagas_elegiveis,
    key=lambda vaga: vaga["score"],
    reverse=True
)

novas_relevantes = [
    vaga
    for vaga in vagas_novas
    if vaga["status_localizacao"] == "elegivel"
    and vaga["score"] >= SCORE_MINIMO
]

print(f"Vagas coletadas: {len(vagas_coletadas)}")
print(f"Vagas únicas: {len(vagas)}")
print(f"Duplicadas removidas: {len(vagas_coletadas) - len(vagas)}")
print(f"Vagas da área: {len(vagas_filtradas)}")
print(f"Novas vagas relevantes: {len(novas_relevantes)}")
print(f"Novas salvas no banco: {len(vagas_novas)}")
print(f"Já existentes atualizadas: {atualizadas}")

print(f"Elegíveis com score >= {SCORE_MINIMO}: {len(vagas_elegiveis)}")
print(f"Elegíveis com score baixo: {len(vagas_score_baixo)}")
print(f"Localização incerta: {len(vagas_incertas)}")
print(f"Inelegíveis: {len(vagas_inelegiveis)}")

print("\nTOP VAGAS ELEGÍVEIS\n")


for vaga in vagas_ordenadas[:10]:
    print("-" * 60)
    print(f"Score: {vaga['score']}/100")
    print("Cargo:", vaga["title"])
    print("Empresa:", vaga["company_name"])
    print("Localização:", vaga["location"])
    print("Remoto:", vaga["remote"])
    print("Fonte:", vaga["source"])
    print("Link:", vaga["url"])
    print("Elegibilidade:", vaga["status_localizacao"])
    print("Motivo localização:", vaga["motivo_localizacao"])

    for motivo in vaga["motivos"]:
        print(motivo)