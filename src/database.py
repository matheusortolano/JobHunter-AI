import os

import mysql.connector
from dotenv import load_dotenv


load_dotenv()


def conectar_banco():
    conexao = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        use_pure=True,
    )

    return conexao


def testar_conexao():
    conexao = None
    cursor = None

    try:
        conexao = conectar_banco()
        cursor = conexao.cursor()

        cursor.execute("SELECT 1;")
        resultado = cursor.fetchone()

        if resultado:
            print("Conexão com MySQL realizada com sucesso! ✅")

    except mysql.connector.Error as erro:
        print("Erro ao conectar ao MySQL:")
        print(erro)

    finally:
        if cursor:
            cursor.close()

        if conexao and conexao.is_connected():
            conexao.close()


if __name__ == "__main__":
    testar_conexao()