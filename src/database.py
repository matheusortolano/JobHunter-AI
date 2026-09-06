import json
import os

import mysql.connector
from dotenv import load_dotenv

from deduplicator import gerar_fingerprint


load_dotenv()


def conectar_banco():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        use_pure=True,
    )


def salvar_vaga(cursor, vaga):
    fingerprint = gerar_fingerprint(vaga)

    cursor.execute(
        """
        SELECT id
        FROM vagas
        WHERE fingerprint = %s
        """,
        (fingerprint,),
    )

    vaga_existente = cursor.fetchone()

    motivos_score = json.dumps(
        vaga.get("motivos", []),
        ensure_ascii=False,
    )

    if vaga_existente:
        cursor.execute(
            """
            UPDATE vagas
            SET
                titulo = %s,
                empresa = %s,
                localizacao = %s,
                remoto = %s,
                fonte = %s,
                url = %s,
                descricao = %s,
                score = %s,
                status_localizacao = %s,
                motivo_localizacao = %s,
                motivos_score = %s,
                ultima_visualizacao = CURRENT_TIMESTAMP
            WHERE fingerprint = %s
            """,
            (
                vaga.get("title", ""),
                vaga.get("company_name", ""),
                vaga.get("location", ""),
                vaga.get("remote", False),
                vaga.get("source", ""),
                vaga.get("url", ""),
                vaga.get("description", ""),
                vaga.get("score", 0),
                vaga.get("status_localizacao", ""),
                vaga.get("motivo_localizacao", ""),
                motivos_score,
                fingerprint,
            ),
        )

        return "atualizada"

    cursor.execute(
        """
        INSERT INTO vagas (
            titulo,
            empresa,
            localizacao,
            remoto,
            fonte,
            url,
            descricao,
            score,
            status_localizacao,
            motivo_localizacao,
            motivos_score,
            fingerprint
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            vaga.get("title", ""),
            vaga.get("company_name", ""),
            vaga.get("location", ""),
            vaga.get("remote", False),
            vaga.get("source", ""),
            vaga.get("url", ""),
            vaga.get("description", ""),
            vaga.get("score", 0),
            vaga.get("status_localizacao", ""),
            vaga.get("motivo_localizacao", ""),
            motivos_score,
            fingerprint,
        ),
    )

    return "nova"


def salvar_vagas(vagas):
    conexao = None
    cursor = None

    vagas_novas = []
    atualizadas = 0

    try:
        conexao = conectar_banco()
        cursor = conexao.cursor()

        for vaga in vagas:
            resultado = salvar_vaga(cursor, vaga)

            vaga["status_banco"] = resultado

            if resultado == "nova":
                vagas_novas.append(vaga)
            else:
                atualizadas += 1

        conexao.commit()

        return vagas_novas, atualizadas

    except mysql.connector.Error as erro:
        if conexao:
            conexao.rollback()

        print("Erro ao salvar vagas no MySQL:")
        print(erro)

        return [], 0

    finally:
        if cursor:
            cursor.close()

        if conexao and conexao.is_connected():
            conexao.close()

def testar_conexao():
    conexao = None

    try:
        conexao = conectar_banco()
        print("Conexão com MySQL realizada com sucesso! ✅")

    except mysql.connector.Error as erro:
        print("Erro ao conectar ao MySQL:")
        print(erro)

    finally:
        if conexao and conexao.is_connected():
            conexao.close()

def buscar_melhor_vaga():
    conexao = None
    cursor = None

    try:
        conexao = conectar_banco()
        cursor = conexao.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                id,
                titulo AS title,
                empresa AS company_name,
                localizacao AS location,
                descricao AS description,
                score
            FROM vagas
            WHERE status_localizacao = 'elegivel'
              AND score >= 40
              AND analisada_ia = FALSE
            ORDER BY score DESC
            LIMIT 1
            """
        )

        return cursor.fetchone()

    finally:
        if cursor:
            cursor.close()

        if conexao and conexao.is_connected():
            conexao.close()

def salvar_analise_ia(vaga_id, analise):
    conexao = None
    cursor = None

    try:
        conexao = conectar_banco()
        cursor = conexao.cursor()

        pontos_fortes = json.dumps(
            analise.get("pontos_fortes", []),
            ensure_ascii=False,
        )

        gaps = json.dumps(
            analise.get("gaps", []),
            ensure_ascii=False,
        )

        cursor.execute(
            """
            UPDATE vagas
            SET
                score_ia = %s,
                recomendacao_ia = %s,
                pontos_fortes_ia = %s,
                gaps_ia = %s,
                justificativa_ia = %s,
                analisada_ia = TRUE,
                data_analise_ia = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                analise.get("score_ia"),
                analise.get("recomendacao"),
                pontos_fortes,
                gaps,
                analise.get("justificativa"),
                vaga_id,
            ),
        )

        conexao.commit()

        print("Análise da IA salva no MySQL! ✅")

    except mysql.connector.Error as erro:
        if conexao:
            conexao.rollback()

        print("Erro ao salvar análise da IA:")
        print(erro)

    finally:
        if cursor:
            cursor.close()

        if conexao and conexao.is_connected():
            conexao.close()

if __name__ == "__main__":
    testar_conexao()