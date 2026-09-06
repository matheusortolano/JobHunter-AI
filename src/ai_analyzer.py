import os

from dotenv import load_dotenv
from google import genai


load_dotenv()


def testar_gemini():
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("Erro: GEMINI_API_KEY não encontrada no .env")
        return

    client = genai.Client(api_key=api_key)

    resposta = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=(
            "Responda apenas com uma frase curta em português: "
            "o JobHunter AI está conectado ao Gemini?"
        ),
    )

    print(resposta.text)


if __name__ == "__main__":
    testar_gemini()