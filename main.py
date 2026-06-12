import hashlib
import os
from html import escape
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError


load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

app = FastAPI(title="API Fichiers Azure")

CONTAINER_NAME = "fichiers-api"


def get_container_client(create_if_missing: bool = False):
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

    if not connection_string:
        raise HTTPException(
            status_code=500,
            detail="La variable AZURE_STORAGE_CONNECTION_STRING est manquante.",
        )

    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)

    if create_if_missing:
        try:
            container_client.create_container()
        except Exception:
            pass

    return container_client


def get_db_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise HTTPException(
            status_code=500,
            detail="La variable DATABASE_URL est manquante.",
        )

    return psycopg2.connect(database_url)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_user_by_login(login: str):
    try:
        with get_db_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id, login, mot_de_passe FROM utilisateur WHERE login = %s",
                    (login,),
                )
                return cursor.fetchone()
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur base de données : {error}",
        )


def log_file_action(login: str, action: str, filename: str) -> None:
    try:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM utilisateur WHERE login = %s",
                    (login,),
                )
                user = cursor.fetchone()

                if not user:
                    return

                cursor.execute(
                    """
                    INSERT INTO log_file (id_user, action, lien_blob)
                    VALUES (%s, %s, %s)
                    """,
                    (user[0], action, filename),
                )

            connection.commit()

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'ajout du log : {error}",
        )


def upload_to_blob(file: UploadFile, login: str = "anonymous") -> dict:
    container_client = get_container_client(create_if_missing=True)

    if not file.filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")

    try:
        blob_client = container_client.get_blob_client(file.filename)
        blob_client.upload_blob(file.file, overwrite=True)

        log_file_action(login, "upload", file.filename)

        return {
            "message": "Fichier envoyé avec succès.",
            "filename": file.filename,
            "user": login,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'upload : {error}",
        )


def delete_blob(filename: str, login: str = "anonymous") -> dict:
    container_client = get_container_client()

    if not filename:
        raise HTTPException(status_code=400, detail="Nom de fichier manquant.")

    try:
        blob_client = container_client.get_blob_client(filename)
        blob_client.delete_blob()

        log_file_action(login, "delete", filename)

        return {
            "message": "Fichier supprimé avec succès.",
            "filename": filename,
            "user": login,
        }

    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la suppression : {error}",
        )


@app.get("/", response_class=HTMLResponse)
def upload_page(status: str = "", filename: str = "") -> str:
    try:
        files = list_files()["files"]
    except Exception:
        files = []

    safe_status = escape(status)
    safe_filename = escape(filename)

    files_html = ""

    if files:
        for file_name in files:
            safe_file_name = escape(file_name)
            files_html += f"""
                <li>
                    <span>{safe_file_name}</span>
                    <form method="post" action="/delete" style="display:inline;">
                        <input type="hidden" name="filename" value="{safe_file_name}">
                        <input type="hidden" name="login" value="anonymous">
                        <button type="submit">Supprimer</button>
                    </form>
                </li>
            """
    else:
        files_html = "<li>Aucun fichier dans le conteneur.</li>"

    message_html = ""
    if safe_status:
        message_html = f"<p><strong>{safe_status}</strong> {safe_filename}</p>"

    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <title>API Fichiers Azure</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 40px auto;
                padding: 20px;
                background: #f7f7f7;
            }}

            h1, h2 {{
                color: #222;
            }}

            form {{
                margin-bottom: 20px;
            }}

            input {{
                margin-bottom: 8px;
                padding: 6px;
            }}

            button {{
                cursor: pointer;
                padding: 6px 12px;
            }}

            li {{
                margin-bottom: 10px;
            }}

            .card {{
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
                margin-bottom: 20px;
            }}
        </style>
    </head>
    <body>
        <h1>API Fichiers Azure</h1>

        {message_html}

        <div class="card">
            <h2>Créer un utilisateur</h2>
            <form method="post" action="/register">
                <input type="text" name="login" placeholder="Login" required><br>
                <input type="password" name="password" placeholder="Mot de passe" required><br>
                <button type="submit">Créer le compte</button>
            </form>
        </div>

        <div class="card">
            <h2>Connexion</h2>
            <form method="post" action="/login">
                <input type="text" name="login" placeholder="Login" required><br>
                <input type="password" name="password" placeholder="Mot de passe" required><br>
                <button type="submit">Se connecter</button>
            </form>
        </div>

        <div class="card">
            <h2>Envoyer un fichier</h2>
            <form method="post" action="/" enctype="multipart/form-data">
                <input type="text" name="login" placeholder="Login utilisateur" value="anonymous" required><br>
                <input type="file" name="file" required><br>
                <button type="submit">Envoyer</button>
            </form>
        </div>

        <div class="card">
            <h2>Fichiers présents dans Azure Blob Storage</h2>
            <ul>
                {files_html}
            </ul>
        </div>

        <p>
            Documentation API : <a href="/docs">/docs</a>
        </p>
    </body>
    </html>
    """


@app.post("/register")
def register_user(login: str = Form(...), password: str = Form(...)):
    password_hash = hash_password(password)

    try:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO utilisateur (login, mot_de_passe)
                    VALUES (%s, %s)
                    """,
                    (login, password_hash),
                )

            connection.commit()

        return RedirectResponse(
            url=f"/?status=Utilisateur créé :&filename={login}",
            status_code=303,
        )

    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="Ce login existe déjà.")

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la création de l'utilisateur : {error}",
        )


@app.post("/login")
def login_user(login: str = Form(...), password: str = Form(...)):
    user = get_user_by_login(login)

    if not user:
        raise HTTPException(status_code=401, detail="Identifiants invalides.")

    if user["mot_de_passe"] != hash_password(password):
        raise HTTPException(status_code=401, detail="Identifiants invalides.")

    try:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE utilisateur
                    SET derniere_connexion = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (user["id"],),
                )

            connection.commit()

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la mise à jour de la connexion : {error}",
        )

    return {
        "message": "Connexion réussie.",
        "user": login,
    }


@app.post("/")
def upload_from_root(
    file: UploadFile = File(...),
    login: str = Form("anonymous"),
):
    result = upload_to_blob(file, login)

    return RedirectResponse(
        url=f"/?status=Fichier envoyé :&filename={result['filename']}",
        status_code=303,
    )


@app.get("/files")
def list_files() -> dict:
    container_client = get_container_client(create_if_missing=True)

    try:
        blobs = container_client.list_blobs()
        files = [blob.name for blob in blobs]

        return {"files": files}

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du listing : {error}",
        )


@app.post("/delete")
def delete_from_root(
    filename: str = Form(...),
    login: str = Form("anonymous"),
):
    delete_blob(filename, login)

    return RedirectResponse(
        url=f"/?status=Fichier supprimé :&filename={filename}",
        status_code=303,
    )


@app.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    login: str = Form("anonymous"),
) -> dict:
    return upload_to_blob(file, login)


@app.delete("/remove")
def remove_file(filename: str, login: str = "anonymous") -> dict:
    return delete_blob(filename, login)


@app.get("/logs")
def list_logs() -> dict:
    try:
        with get_db_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        log_file.id,
                        utilisateur.login,
                        log_file.action,
                        log_file.lien_blob,
                        log_file.date
                    FROM log_file
                    JOIN utilisateur ON utilisateur.id = log_file.id_user
                    ORDER BY log_file.date DESC
                    """
                )
                logs = cursor.fetchall()

        return {"logs": logs}

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération des logs : {error}",
        )