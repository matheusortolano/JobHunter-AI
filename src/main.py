from collector import buscar_todas_vagas
from filters import filtrar_vagas
from scorer import calcular_score


vagas = buscar_todas_vagas()
vagas_filtradas = filtrar_vagas(vagas)

for vaga in vagas_filtradas:
    vaga["score"], vaga["motivos"] = calcular_score(vaga)

vagas_ordenadas = sorted(
    vagas_filtradas,
    key=lambda vaga: vaga["score"],
    reverse=True
)

print(f"Vagas coletadas: {len(vagas)}")
print(f"Vagas após filtro: {len(vagas_filtradas)}")

for vaga in vagas_ordenadas[:10]:
    print("-" * 60)
    print(f"Score: {vaga['score']}/100")
    print("Cargo:", vaga["title"])
    print("Empresa:", vaga["company_name"])
    print("Localização:", vaga["location"])
    print("Remoto:", vaga["remote"])
    print("Fonte:", vaga["source"])
    print("Link:", vaga["url"])

    for motivo in vaga["motivos"]:
        print(motivo)