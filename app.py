from flask import Flask, render_template, request, redirect
from flask_cors import CORS
from pymongo import MongoClient
from dotenv import load_dotenv
import jwt
from functools import wraps
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os
import mimetypes
import re

# Cargar variables de entorno
load_dotenv()
MONGO_URI = os.getenv('MONGO_URI')
DB_NAME = os.getenv('DB_NAME')
COLLECTION_NAME = os.getenv('COLLECTION_NAME')
JWT_SECRET = os.getenv('JWT_SECRET')
DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID')

# Conexión a MongoDB
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

app = Flask(__name__)
CORS(app)

# Configurar cliente de Google Drive
def get_drive_service():
    creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/drive.readonly'])
    return build('drive', 'v3', credentials=creds)

# Decorador para verificar JWT
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return {"error": "Token requerido"}, 401
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            request.user_id = payload.get('id')
        except jwt.ExpiredSignatureError:
            return {"error": "Token expirado"}, 401
        except jwt.InvalidTokenError:
            return {"error": "Token inválido"}, 401
        return f(*args, **kwargs)
    return decorated

# Ruta para sincronizar películas desde Google Drive
@app.route('/sync-movies', methods=['POST'])
@require_auth
def sync_movies():
    try:
        service = get_drive_service()
        # Buscar archivos en la carpeta de Google Drive
        query = f"'{DRIVE_FOLDER_ID}' in parents and mimeType contains 'video/'"
        results = service.files().list(q=query, fields="files(id, name, webContentLink, mimeType)").execute()
        files = results.get('files', [])

        for file in files:
            file_name = file['name']
            file_id = file['id']
            web_content_link = file.get('webContentLink')
            # Extraer título limpio (sin extensión)
            title = re.sub(r'\.[^.]+$', '', file_name)
            # Verificar si la película ya existe
            exists = collection.find_one({'drive_file_id': file_id})
            if not exists:
                # Insertar metadatos en MongoDB
                movie = {
                    'titulo': title,
                    'descripcion': f"Descripción de {title} (autogenerada)",
                    'duracion': 'Desconocida',  # Necesitarías una API para obtener duración
                    'generos': ['Género desconocido'],
                    'miniatura': 'https://via.placeholder.com/224x126.png?text=Sin+Imagen',
                    'url_video': web_content_link,
                    'drive_file_id': file_id,
                    'anio': '2023'  # Valor por defecto
                }
                collection.insert_one(movie)
                print(f"Película '{title}' insertada en MongoDB")
            else:
                print(f"Película '{title}' ya existe en MongoDB")

        return {"message": "Sincronización completada"}, 200
    except Exception as e:
        print(f"Error en sincronización: {e}")
        return {"error": f"Error en sincronización: {e}"}, 500

@app.route('/video')
@require_auth
def video():
    nombre = request.args.get('nombre')
    if not nombre:
        return "Falta el parámetro 'nombre'", 400
    doc = collection.find_one({'titulo': nombre})
    if not doc:
        return f"No se encontró el video '{nombre}'", 404
    url_video = doc.get('url_video')
    if url_video:
        return redirect(url_video)
    return f"No se encontró URL para '{nombre}'", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9090, debug=True)