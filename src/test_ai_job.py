from ai_analyzer import AnalisePendente, analisar_vaga
from database import buscar_melhor_vaga, salvar_analise_ia


vaga = buscar_melhor_vaga()

if not vaga:
    print("Nenhuma vaga pendente de análise pela IA.")

else:
    print("Analisando:")
    print(vaga["title"])

    try:
        resultado = analisar_vaga(vaga)

    except AnalisePendente as erro:
        print("\nAnálise adiada:")
        print(erro)
        print("Nenhuma análise foi salva no banco.")

    else:
        print("\nRESULTADO DA IA\n")

        print(f"Score algoritmo: {vaga['score']}/100")
        print(f"Score IA: {resultado['score_ia']}/100")
        print("Recomendação:", resultado["recomendacao"])

        print("\nPontos fortes:")

        for ponto in resultado["pontos_fortes"]:
            print("+", ponto)

        print("\nGaps:")

        for gap in resultado["gaps"]:
            print("-", gap)

        print("\nJustificativa:")
        print(resultado["justificativa"])

        salvar_analise_ia(
            vaga["id"],
            resultado,
        )