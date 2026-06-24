# Revisión de seguridad, lógica y arquitectura

## Resumen ejecutivo

La app es un asistente comunal basado en FastAPI, SQLite, frontend estático, generación de cartas/informes, búsqueda documental y bots externos. La base es útil para operar localmente, pero antes de exponerla a internet conviene reforzar autenticación, autorización por roles, validación de entradas, gobierno de datos personales y observabilidad.

## Riesgos prioritarios detectados

1. **Autenticación opcional**: si `API_KEY` está vacío, las rutas `/api/*` quedan abiertas. Para producción debe ser obligatorio y debería evolucionar a usuarios con roles.
2. **Autorización inexistente por función**: cualquier cliente autenticado puede crear, editar, borrar, indexar, consultar documentos o generar cartas.
3. **Datos sensibles**: padrón, voceros, cartas, tareas y documentos pueden contener información personal. Falta política de retención, exportación, auditoría y minimización.
4. **Superficie de archivos**: cargas, archivos generados y exploración de carpetas requieren límites estrictos para evitar lectura/escritura fuera de rutas esperadas.
5. **Operaciones costosas**: indexación, OCR, búsquedas universales y llamadas de IA pueden consumir recursos o cuota sin rate limiting.
6. **Frontend monolítico**: hay mucha lógica inline en `index.html`; eso dificulta pruebas, mantenimiento y control de XSS.

## Cambios aplicados en esta revisión

- Comparación de API key con `secrets.compare_digest` para evitar comparaciones vulnerables a timing attacks.
- Validación más estricta de fotos subidas: extensión permitida, `Content-Type`, tamaño máximo, verificación real con Pillow y coincidencia entre extensión y formato detectado.
- La API de carga de fotos devuelve una ruta pública relativa (`/media/...`) y el nombre generado, en vez de exponer rutas absolutas del sistema.
- La búsqueda universal por carpeta queda limitada al árbol configurado en `DOCUMENTOS_COMUNA_PATH`.

## Recomendaciones de seguridad

### Corto plazo

- Hacer obligatoria la autenticación en producción: fallar el arranque si `API_KEY` está vacío y `ENV=production`.
- Separar permisos: administración, carga de documentos, consulta, reportes, padrón y solo lectura.
- Añadir rate limiting por IP/usuario para `/api/search`, `/api/agent/query`, `/api/universal/*`, `/api/documents/index` y cargas de archivos.
- Limitar tamaño del body HTTP de forma global en proxy o ASGI server.
- Registrar auditoría de acciones críticas: crear/editar/borrar actividades, padrón, cartas, consultas, exportaciones e indexación.
- Evitar devolver detalles internos en errores 500; registrar el detalle solo en logs.
- Excluir bases locales, media y documentos generados del repositorio si contienen datos reales.

### Medio plazo

- Implementar login con sesiones seguras o JWT de corta duración y refresh tokens rotados.
- Agregar CSRF si se usan cookies; mantener `Authorization: Bearer` si se consume como SPA/API.
- Cifrar secretos en despliegue con un secret manager o variables protegidas.
- Añadir antivirus o sandbox para archivos cargados si habrá usuarios no confiables.
- Crear una matriz de clasificación de datos y enmascarar información personal en logs.
- Centralizar validaciones Pydantic con límites de longitud, fechas válidas y rangos numéricos.

## Recomendaciones de lógica de negocio

- Validar `fecha` y `fecha_limite` con tipos `date`/`datetime` en Pydantic en vez de strings libres.
- Rechazar participantes negativos y descripciones vacías cuando la operación lo requiera.
- Evitar categorías duplicadas por diferencias de mayúsculas, acentos o espacios.
- Hacer idempotente la indexación y exponer estado/progreso para evitar múltiples indexaciones simultáneas.
- Añadir control de versiones para cartas e informes generados.
- Agregar pruebas sobre flujos principales: actividades, padrón, cartas, tareas, uploads, búsqueda y exportación.

## Recomendaciones de arquitectura

- Separar capas: routers (`backend/api`), servicios (`backend/services`), repositorios (`backend/repositories`) y modelos/esquemas (`backend/schemas`).
- Reducir `backend/main.py` a composición de app, middleware y routers.
- Mover lógica inline del frontend a módulos JavaScript separados y reutilizables.
- Crear configuración por ambiente (`development`, `test`, `production`) con defaults seguros.
- Añadir migraciones de base de datos formales en lugar de migraciones manuales dentro de inicialización.
- Instrumentar métricas: latencia por endpoint, errores, cola de indexación, uso de IA y tamaño de documentos.
- Contener tareas pesadas en workers dedicados (RQ/Celery/Arq) en vez de `BackgroundTasks` si crecerá el uso.

## Plan sugerido para potenciar la app

1. **Modo producción seguro**: auth obligatoria, roles, rate limiting, auditoría y backups.
2. **Experiencia de gestión**: filtros avanzados, estados de tareas, tablero de vencimientos y trazabilidad de acuerdos.
3. **IA confiable**: respuestas con citas de documentos, evaluación de calidad, caché y presupuestos de tokens por usuario.
4. **Gestión documental**: etiquetas, permisos por carpeta, deduplicación, OCR incremental y vista previa segura.
5. **Reportería**: plantillas editables, exportación a PDF/DOCX/XLSX y firmas/validaciones de documentos.
6. **Calidad técnica**: tests automatizados, CI, linting, tipado, migraciones y documentación de despliegue.
