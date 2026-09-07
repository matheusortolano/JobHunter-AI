from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


RAIZ = Path(__file__).resolve().parent.parent
CREDENCIAIS = RAIZ / "credentials"

ARQUIVO_CLIENTE = CREDENCIAIS / "gmail_oauth_client.json"
ARQUIVO_TOKEN = CREDENCIAIS / "gmail_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
]


def autorizar_gmail():
    if not ARQUIVO_CLIENTE.exists():
        raise FileNotFoundError(
            "Arquivo credentials/gmail_oauth_client.json não encontrado."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(ARQUIVO_CLIENTE),
        SCOPES,
    )

    credenciais = flow.run_local_server(
        port=0,
        open_browser=True,
    )

    CREDENCIAIS.mkdir(parents=True, exist_ok=True)

    ARQUIVO_TOKEN.write_text(
        credenciais.to_json(),
        encoding="utf-8",
    )

    print("\nGmail autorizado com sucesso.")
    print("Token salvo localmente em credentials/gmail_token.json.")
    print("Nenhum e-mail foi enviado.")


if __name__ == "__main__":
    autorizar_gmail()