from ai_analyzer import analisar_vaga
from database import buscar_melhor_vaga


vaga = buscar_melhor_vaga()

if not vaga:
    print("Nenhuma vaga encontrada.")
else:
    print("Analisando:")
    print(vaga["title"])

    resultado = analisar_vaga(vaga)

    print("\nRESULTADO DA IA\n")

    print(
        f"Score IA: "
        f"{resultado['score_ia']}/100"
    )

    print(
        "Recomendação:",
        resultado["recomendacao"]
    )

    print("\nPontos fortes:")

    for ponto in resultado["pontos_fortes"]:
        print("+", ponto)

    print("\nGaps:")

    for gap in resultado["gaps"]:
        print("-", gap)

    print("\nJustificativa:")
    print(resultado["justificativa"])