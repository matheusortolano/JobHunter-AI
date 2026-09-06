from collector import buscar_vagas
from filters import filtrar_vagas


vagas = buscar_vagas()
vagas_filtradas = filtrar_vagas(vagas)

print(f"Vagas coletadas: {len(vagas)}")
print(f"Vagas após filtro: {len(vagas_filtradas)}")

for vaga in vagas_filtradas[:10]:
    print("-" * 50)
    print("Cargo:", vaga["title"])
    print("Empresa:", vaga["company_name"])
    print("Localização:", vaga["location"])
    print("Remoto:", vaga["remote"])