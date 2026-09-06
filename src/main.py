from collector import buscar_todas_vagas
from filters import filtrar_vagas
from scorer import calcular_score
from location import analisar_localizacao


SCORE_MINIMO = 40


vagas = buscar_todas_vagas()
vagas_filtradas = filtrar_vagas(vagas)


for vaga in vagas_filtradas:
    vaga["score"], vaga["motivos"] = calcular_score(vaga)

    status_localizacao, motivo_localizacao = analisar_localizacao(vaga)

    vaga["status_localizacao"] = status_localizacao
    vaga["motivo_localizacao"] = motivo_localizacao


# Vagas elegíveis e com score mínimo
vagas_elegiveis = [
    vaga
    for vaga in vagas_filtradas
    if vaga["status_localizacao"] == "elegivel"
    and vaga["score"] >= SCORE_MINIMO
]


# Vagas remotas/localização que ainda precisam de análise
vagas_incertas = [
    vaga
    for vaga in vagas_filtradas
    if vaga["status_localizacao"] == "incerto"
]


# Vagas que não atendem nossa regra geográfica
vagas_inelegiveis = [
    vaga
    for vaga in vagas_filtradas
    if vaga["status_localizacao"] == "inelegivel"
]


# Ordena as vagas elegíveis da maior pontuação para a menor
vagas_ordenadas = sorted(
    vagas_elegiveis,
    key=lambda vaga: vaga["score"],
    reverse=True
)


print(f"Vagas coletadas: {len(vagas)}")
print(f"Vagas da área: {len(vagas_filtradas)}")
print(f"Elegíveis com score >= {SCORE_MINIMO}: {len(vagas_elegiveis)}")
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