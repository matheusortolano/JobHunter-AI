from collector import buscar_vagas


vagas = buscar_vagas()

print(f"Total de vagas encontradas: {len(vagas)}")

for vaga in vagas[:5]:
    print("-" * 50)
    print("Cargo:", vaga["title"])
    print("Empresa:", vaga["company_name"])
    print("Localização:", vaga["location"])
    print("Remoto:", vaga["remote"])