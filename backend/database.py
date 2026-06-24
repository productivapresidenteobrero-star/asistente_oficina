import sqlite3
import aiosqlite
import json
from datetime import datetime
from backend.config import DATABASE_PATH, CATEGORIAS_ACTIVIDADES
import logging

logger = logging.getLogger("database")

from contextlib import asynccontextmanager

@asynccontextmanager
async def _get_db_cm():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db

async def get_db():
    """Retorna un context manager asíncrono para la base de datos SQLite."""
    return _get_db_cm()

async def init_db():
    """Inicializa la base de datos y crea las tablas si no existen."""
    async with await get_db() as db:
        # Habilitar claves foráneas
        await db.execute("PRAGMA foreign_keys = ON;")
        
        # Tabla de categorías de actividades (permite personalización)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL
        );
        """)
        
        # Tabla de actividades comunales
        await db.execute("""
        CREATE TABLE IF NOT EXISTS actividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL, -- Formato YYYY-MM-DD
            categoria TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            participantes INTEGER DEFAULT 0,
            fotos TEXT DEFAULT '[]', -- Lista JSON de rutas de archivos de imágenes
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # Tabla de cartas y correspondencia
        await db.execute("""
        CREATE TABLE IF NOT EXISTS cartas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_oficio TEXT UNIQUE NOT NULL, -- CPPO-YYYY-Nro.XXX
            tipo TEXT NOT NULL, -- Solicitud, Convocatoria, etc.
            fecha TEXT NOT NULL,
            destinatario TEXT NOT NULL,
            asunto TEXT NOT NULL,
            contenido TEXT NOT NULL,
            pdf_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # Tabla de tareas programadas (alertas/calendario)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tareas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descripcion TEXT,
            fecha_limite TEXT NOT NULL, -- YYYY-MM-DD HH:MM
            recordatorio_dias INTEGER DEFAULT 1, -- Días de anticipación para avisar
            sincronizado_calendar INTEGER DEFAULT 0, -- 0 = No, 1 = Sí
            telegram_notificado INTEGER DEFAULT 0, -- 0 = No, 1 = Sí
            completada INTEGER DEFAULT 0, -- 0 = Pendiente, 1 = Completada
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # Tabla de control de documentos indexados
        await db.execute("""
        CREATE TABLE IF NOT EXISTS documentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            ruta TEXT UNIQUE NOT NULL,
            tipo_documento TEXT, -- PDF, DOCX, XLSX, TXT, IMG
            hash_archivo TEXT, -- Para evitar re-indexar si no ha cambiado
            fecha_indexado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # Insertar categorías predeterminadas si está vacío
        cursor = await db.execute("SELECT COUNT(*) FROM categorias")
        count = (await cursor.fetchone())[0]
        if count == 0:
            for cat in CATEGORIAS_ACTIVIDADES:
                await db.execute("INSERT OR IGNORE INTO categorias (nombre) VALUES (?)", (cat,))
        
        # ── PADRÓN DE CONSEJOS COMUNALES Y VOCEROS ─────────────────────────────
        await db.execute("""
        CREATE TABLE IF NOT EXISTS consejos_comunales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            rif TEXT,
            sector TEXT,
            fecha_constitucion TEXT,
            vocero_coordinador TEXT,
            telefono TEXT,
            email TEXT,
            activo INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS voceros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consejo_id INTEGER,
            nombre TEXT NOT NULL,
            cedula TEXT,
            cargo TEXT NOT NULL,
            telefono TEXT,
            email TEXT,
            activo INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (consejo_id) REFERENCES consejos_comunales(id)
        );
        """)

        # ── CONSULTAS POPULARES ─────────────────────────────────────────────────
        await db.execute("""
        CREATE TABLE IF NOT EXISTS consultas_populares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descripcion TEXT,
            fecha_inicio TEXT NOT NULL,
            fecha_cierre TEXT NOT NULL,
            estado TEXT DEFAULT 'activa',  -- activa, cerrada, archivada
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS preguntas_consulta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consulta_id INTEGER NOT NULL,
            texto TEXT NOT NULL,
            tipo TEXT DEFAULT 'si_no',  -- si_no, multiple, texto
            opciones TEXT DEFAULT '[]',  -- JSON array de opciones para tipo 'multiple'
            FOREIGN KEY (consulta_id) REFERENCES consultas_populares(id)
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS respuestas_consulta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pregunta_id INTEGER NOT NULL,
            participante TEXT,  -- nombre o cédula (anónimo si NULL)
            respuesta TEXT NOT NULL,
            fecha TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pregunta_id) REFERENCES preguntas_consulta(id)
        );
        """)

        # ── ACTAS DE ELECCIÓN ────────────────────────────────────────────────────
        await db.execute("""
        CREATE TABLE IF NOT EXISTS actas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_registro TEXT UNIQUE,
            fecha_acta TEXT NOT NULL,
            consejo_id INTEGER,
            nombre_consejo TEXT NOT NULL,
            sector TEXT,
            pdf_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (consejo_id) REFERENCES consejos_comunales(id)
        );
        """)

        # ── SCHEMA VERSION CONTROL ────────────────────────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor = await db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        row = await cursor.fetchone()
        current_ver = row[0] if row else 0

        if current_ver < 1:
            # v1: add tipo, acta_id, votos columns + remove UNIQUE from cedula

            # Safe ALTER TABLE for new columns (fails silently if exists)
            for col_sql in [
                "ALTER TABLE voceros ADD COLUMN tipo TEXT DEFAULT 'Principal'",
                "ALTER TABLE voceros ADD COLUMN acta_id INTEGER REFERENCES actas(id)",
                "ALTER TABLE voceros ADD COLUMN votos INTEGER DEFAULT 0",
            ]:
                try:
                    await db.execute(col_sql)
                except Exception:
                    pass

            # Check if UNIQUE constraint still exists on cedula (old schema)
            c2 = await db.execute("PRAGMA index_list(voceros)")
            indexes = await c2.fetchall()
            has_unique_cedula = len(indexes) > 0

            if has_unique_cedula:
                # Rebuild table without UNIQUE, deduplicating any prior doubling
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS voceros_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        consejo_id INTEGER,
                        nombre TEXT NOT NULL,
                        cedula TEXT,
                        cargo TEXT NOT NULL,
                        telefono TEXT,
                        email TEXT,
                        tipo TEXT DEFAULT 'Principal',
                        acta_id INTEGER,
                        votos INTEGER DEFAULT 0,
                        activo INTEGER DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (consejo_id) REFERENCES consejos_comunales(id),
                        FOREIGN KEY (acta_id) REFERENCES actas(id)
                    )
                """)
                # Deduplicate on data columns (exclude id) to fix prior doubling
                await db.execute("""
                    INSERT INTO voceros_new (consejo_id, nombre, cedula, cargo, telefono, email,
                                             tipo, acta_id, votos, activo, created_at)
                    SELECT DISTINCT consejo_id, nombre, cedula, cargo, telefono, email,
                                    COALESCE(tipo, 'Principal'), acta_id, COALESCE(votos, 0),
                                    activo, created_at
                    FROM voceros
                """)
                await db.execute("DROP TABLE voceros")
                await db.execute("ALTER TABLE voceros_new RENAME TO voceros")
                logger.info("Migración v1: UNIQUE de cedula eliminado y datos deduplicados")

            await db.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (1)")

        if current_ver < 2:
            # v2: tracking de compromisos en tareas
            for col_sql in [
                "ALTER TABLE tareas ADD COLUMN responsable TEXT",
                "ALTER TABLE tareas ADD COLUMN consejo_id INTEGER REFERENCES consejos_comunales(id)",
                "ALTER TABLE tareas ADD COLUMN estado TEXT DEFAULT 'pendiente'",
            ]:
                try:
                    await db.execute(col_sql)
                except Exception:
                    pass
            
            try:
                await db.execute("UPDATE tareas SET estado = 'completada' WHERE completada = 1")
            except Exception:
                pass

            await db.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (2)")
            logger.info("Migración v2: Campos de seguimiento agregados a tareas")

        # Safe column additions for cartas (always run, fail silently if exists)
        for col_sql in [
            "ALTER TABLE cartas ADD COLUMN docx_path TEXT",
            "ALTER TABLE cartas ADD COLUMN vocero_firma TEXT",
        ]:
            try:
                await db.execute(col_sql)
            except Exception:
                pass

        # ── PERSISTENCIA DE CUOTAS DE IA ────────────────────────────────────────
        await db.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,           -- YYYY-MM-DD
            proveedor TEXT NOT NULL,       -- groq, gemini, cohere, huggingface
            llamadas INTEGER DEFAULT 0,
            UNIQUE(fecha, proveedor)
        );
        """)

        await db.commit()

async def obtener_siguiente_numero_oficio(prefijo="CPPO"):
    """
    Genera el siguiente número de oficio correlativo continuo (nunca reinicia).
    Formato: CPPO-0001
    """
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT numero_oficio FROM cartas ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        
        if row:
            ultimo_numero = row[0]
            try:
                # Compatibilidad: soporta CPPO-Nro.0001 y CPPO-0001
                if "Nro." in ultimo_numero:
                    secuencia_str = ultimo_numero.split("Nro.")[-1]
                else:
                    secuencia_str = ultimo_numero.split("-")[-1]
                siguiente = int(secuencia_str) + 1
            except Exception:
                siguiente = 1
        else:
            siguiente = 1
            
        return f"{prefijo}-{siguiente:04d}"
