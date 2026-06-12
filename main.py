import os
from html import escape
from pathlib import Path

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


def upload_to_blob(file: UploadFile) -> dict:
    container_client = get_container_client(create_if_missing=True)

    if not file.filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")

    try:
        blob_client = container_client.get_blob_client(file.filename)
        blob_client.upload_blob(file.file, overwrite=True)

        return {
            "message": "Fichier envoyé avec succès.",
            "filename": file.filename,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'upload : {error}",
        )


def delete_blob(filename: str) -> dict:
    container_client = get_container_client()

    if not filename:
        raise HTTPException(status_code=400, detail="Nom de fichier manquant.")

    try:
        blob_client = container_client.get_blob_client(filename)
        blob_client.delete_blob()

        return {
            "message": "Fichier supprimé avec succès.",
            "filename": filename,
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
            <h2>Envoyer un fichier</h2>
            <form method="post" action="/" enctype="multipart/form-data">
                <input type="file" name="file" required>
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


@app.post("/")
def upload_from_root(file: UploadFile = File(...)):
    result = upload_to_blob(file)

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
def delete_from_root(filename: str = Form(...)):
    delete_blob(filename)

    return RedirectResponse(
        url=f"/?status=Fichier supprimé :&filename={filename}",
        status_code=303,
    )


@app.post("/upload")
def upload_file(file: UploadFile = File(...)) -> dict:
    return upload_to_blob(file)


@app.delete("/remove")
def remove_file(filename: str) -> dict:
    return delete_blob(filename)