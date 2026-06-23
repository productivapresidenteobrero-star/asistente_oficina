import os
import logging
from pathlib import Path
from typing import Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from backend.config import GOOGLE_CREDENTIALS_FILE, BASE_DIR
from backend.database import get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calendar_sync")

# Alcances de la API de Google Calendar
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

def obtener_servicio_calendario():
    """Autentica y obtiene el servicio cliente de Google Calendar."""
    creds = None
    token_path = BASE_DIR / 'token.json'
    creds_path = BASE_DIR / GOOGLE_CREDENTIALS_FILE
    
    # El archivo token.json almacena los tokens de acceso y refresco del usuario
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            logger.error(f"Error al cargar token.json existente: {e}")
            
    # Si no hay credenciales válidas disponibles, solicitar al usuario que inicie sesión.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
            except Exception as e:
                logger.error(f"Error al refrescar token de Google: {e}")
                creds = None
                
        if not creds:
            if not creds_path.exists():
                logger.warning(
                    f"No se encontró el archivo de credenciales de Google API '{creds_path}'. "
                    "La sincronización de Google Calendar estará desactivada hasta que se configure."
                )
                return None
                
            try:
                # Flujo local para obtener autorización
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                # Ejecutar servidor local para autenticar. 
                # Nota: En producción/uso real, el usuario debe abrir el enlace de autorización en su navegador.
                # Para evitar bloquear el backend, permitimos ejecutar esto asincrónicamente o indicamos al usuario cómo hacerlo.
                creds = flow.run_local_server(port=0, open_browser=False)
                # Guardar las credenciales para la próxima ejecución
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
            except Exception as e:
                logger.error(f"Fallo al autenticar flujo de Google Calendar OAuth: {e}")
                return None

    try:
        service = build('calendar', 'v3', credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Error al construir cliente de Google Calendar API: {e}")
        return None

async def agregar_evento_calendario(
    titulo: str, 
    descripcion: str, 
    fecha_limite_iso: str, 
    duracion_minutos: int = 60
) -> Optional[str]:
    """
    Crea un evento en el Google Calendar principal de la cuenta configurada.
    fecha_limite_iso: Formato 'YYYY-MM-DDTHH:MM:SS' (por ejemplo, '2026-06-04T12:00:00')
    """
    service = obtener_servicio_calendario()
    if not service:
        logger.warning("Sincronización omitida: Google Calendar no está autenticado.")
        return None
        
    try:
        # Calcular fecha/hora de fin básica
        from datetime import datetime, timedelta
        dt_start = datetime.fromisoformat(fecha_limite_iso)
        dt_end = dt_start + timedelta(minutes=duracion_minutos)
        fecha_fin_iso = dt_end.isoformat()
        
        event = {
            'summary': titulo,
            'description': f"{descripcion}\n\n[Creado automáticamente por Asistente Comunal]",
            'start': {
                'dateTime': f"{fecha_limite_iso}-04:00", # Zona horaria fija de Venezuela (VET, UTC-4)
                'timeZone': 'America/Caracas',
            },
            'end': {
                'dateTime': f"{fecha_fin_iso}-04:00",
                'timeZone': 'America/Caracas',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 60},
                    {'method': 'email', 'minutes': 24 * 60},
                ],
            },
        }
        
        # Insertar evento
        event_result = service.events().insert(calendarId='primary', body=event).execute()
        event_id = event_result.get('id')
        logger.info(f"Evento de Google Calendar creado con éxito: {event_result.get('htmlLink')}")
        return event_id
        
    except Exception as e:
        logger.error(f"Error al insertar evento en Google Calendar: {e}")
        return None

async def sincronizar_tareas_con_calendario():
    """Busca tareas pendientes de sincronización en SQLite y las sube a Google Calendar."""
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT id, titulo, descripcion, fecha_limite FROM tareas WHERE sincronizado_calendar = 0 AND completada = 0"
        )
        tareas_pendientes = await cursor.fetchall()
        
        if not tareas_pendientes:
            return
            
        service = obtener_servicio_calendario()
        if not service:
            return
            
        for tarea in tareas_pendientes:
            t_id = tarea["id"]
            titulo = tarea["titulo"]
            desc = tarea["descripcion"] or ""
            limite = tarea["fecha_limite"] # YYYY-MM-DD HH:MM
            
            # Formatear a ISO8601
            try:
                # Convertir YYYY-MM-DD HH:MM a YYYY-MM-DDTHH:MM:00
                dt = datetime.strptime(limite, "%Y-%m-%d %H:%M")
                fecha_iso = dt.strftime("%Y-%m-%dT%H:%M:00")
            except Exception:
                logger.error(f"Formato de fecha inválido para tarea {t_id}: {limite}")
                continue
                
            logger.info(f"Sincronizando tarea '{titulo}' al calendario...")
            event_id = await agregar_evento_calendario(titulo, desc, fecha_iso)
            
            if event_id:
                await db.execute(
                    "UPDATE tareas SET sincronizado_calendar = 1 WHERE id = ?",
                    (t_id,)
                )
        await db.commit()
