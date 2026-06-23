"""
Configuración central del Asistente Comunal
Comuna Productiva Presidente Obrero
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv(Path(__file__).parent.parent / ".env")


# ============================================================
# Rutas del sistema
# ============================================================
BASE_DIR = Path(__file__).parent.parent
BACKEND_DIR = Path(__file__).parent
DOCUMENTOS_PATH = Path(os.getenv("DOCUMENTOS_COMUNA_PATH", r"D:\Comuna Presidente Obrero"))
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(BACKEND_DIR / "database.db")))
MEDIA_PATH = Path(os.getenv("MEDIA_PATH", str(BASE_DIR / "media")))
INFORMES_PATH = Path(os.getenv("INFORMES_PATH", str(BASE_DIR / "informes_generados")))
CARTAS_PATH = Path(os.getenv("CARTAS_PATH", str(BASE_DIR / "cartas_generadas")))
TEMPLATES_PATH = Path(os.getenv("TEMPLATES_PATH", str(BASE_DIR / "templates")))
CHROMA_PATH = str(BASE_DIR / "chroma_db")

# ============================================================
# APIs de Inteligencia Artificial
# ============================================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")

# Cuotas diarias (solicitudes por día, nivel gratuito)
AI_QUOTAS = {
    "zhipu": {"limit": 5000, "used": 0},
    "groq": {"limit": 14400, "used": 0},
    "gemini": {"limit": 1500, "used": 0},
    "cohere": {"limit": 1000, "used": 0},
    "huggingface": {"limit": 1000, "used": 0},
}

# Orden de prioridad para la rotación
AI_PRIORITY = ["zhipu", "groq", "gemini", "cohere", "huggingface"]

# ============================================================
# Telegram
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============================================================
# Google Calendar
# ============================================================
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_CALENDAR_EMAIL = os.getenv("GOOGLE_CALENDAR_EMAIL", "productivapresidenteobrero@gmail.com")

# Autenticación opcional para API (vacío = desactivada)
API_KEY = os.getenv("API_KEY", "")

# ============================================================
# Servidor Web
# ============================================================
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# ============================================================
# Numeración de Oficios (Cartas)
# Formato: CPPO-2026-Nro.001, CPPO-2026-Nro.002, etc.
# ============================================================
OFICIO_PREFIJO = os.getenv("OFICIO_PREFIJO", "CPPO")

# ============================================================
# Categorías de Actividades (con opción de agregar más)
# ============================================================
CATEGORIAS_ACTIVIDADES = [
    "Asamblea",
    "Consulta Popular",
    "Obra / Construcción",
    "Jornada",
    "Reunión",
    "Visita Institucional",
    "Taller / Formación",
    "Evento Cultural / Deportivo",
    "Rendición de Cuentas",
    "Censo",
    "Otro",
]

# ============================================================
# Tipos de cartas
# ============================================================
TIPOS_CARTAS = [
    "Solicitud",
    "Denuncia",
    "Convocatoria",
    "Oficio",
    "Acta",
    "Informe",
    "Constancia",
    "Comunicado",
    "Otro",
]

# ============================================================
# Idioma
# ============================================================
IDIOMA = "es"  # Español
TESSERACT_LANG = "spa"  # Tesseract OCR en español

# ============================================================
# Información de la Comuna (para membrete de cartas)
# ============================================================
COMUNA_INFO = {
    "nombre": "Comuna Productiva Presidente Obrero",
    "estado": "Mérida",
    "municipio": "",  # Completar
    "parroquia": "",  # Completar
    "rif": "",  # Completar con el RIF de la comuna
    "email": "productivapresidenteobrero@gmail.com",
    "telefono": "",  # Completar
}
