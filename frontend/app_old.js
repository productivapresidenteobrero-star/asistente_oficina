// Configuración base API URL
const API_BASE = "";

// Listas cargadas dinámicamente desde el backend (ver loadLetterTypes en index.html)

function escapeHTML(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

document.addEventListener("DOMContentLoaded", () => {
    // Inicializar Lucide Icons
    if (window.lucide) {
        window.lucide.createIcons();
    }
    
    // Configurar Navegación de Pestañas
    setupTabs();
    
    // Cargar Datos Iniciales
    cargarCategoriasActividades();
    // cargarTiposCartas y cargarCartasEmitidas migradas a index.html inline
    cargarActividadesRegistradas();
    cargarAgendaComunal();
    
    // Registrar Eventos de Formularios
    setupFormularios();
});

// ============================================================
// Navegación de Pestañas
// ============================================================
function setupTabs() {
    const navItems = document.querySelectorAll(".nav-item");
    const tabPanes = document.querySelectorAll(".tab-pane");
    
    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetTab = item.getAttribute("data-tab");
            
            navItems.forEach(nav => nav.classList.remove("active"));
            tabPanes.forEach(pane => pane.classList.remove("active"));
            
            item.classList.add("active");
            document.getElementById(`tab-${targetTab}`).classList.add("active");
            
            // Re-dibujar iconos Lucide si es necesario
            if (window.lucide) {
                window.lucide.createIcons();
            }
        });
    });
}

// ============================================================
// Inicialización de Inputs de Selección (Selects)
// ============================================================
async function cargarCategoriasActividades() {
    const select = document.getElementById("act-category");
    if (!select) return;
    
    try {
        const res = await fetch(`${API_BASE}/api/activities/categories`);
        if (res.ok) {
            const categorias = await res.json();
            select.innerHTML = "";
            categorias.forEach(cat => {
                const option = document.createElement("option");
                option.value = cat;
                option.textContent = cat;
                select.appendChild(option);
            });
        }
    } catch (e) {
        console.error("Error al cargar categorías de actividades:", e);
    }
}

// ============================================================
// Manejadores de Formularios e Interacciones
// ============================================================
function setupFormularios() {
    // 1. Indexador de Documentos
    const btnReindex = document.getElementById("btn-reindex");
    if (btnReindex) {
        btnReindex.addEventListener("click", async () => {
            btnReindex.disabled = true;
            btnReindex.innerHTML = `<i data-lucide="loader" class="animate-spin"></i><span>Indexando...</span>`;
            if (window.lucide) window.lucide.createIcons();
            
            try {
                const res = await fetch(`${API_BASE}/api/documents/index`, { method: "POST" });
                if (res.ok) {
                    alert("Indexación de documentos iniciada en segundo plano.");
                } else {
                    alert("Error al iniciar indexación.");
                }
            } catch (e) {
                alert("Error de conexión al servidor.");
            } finally {
                btnReindex.disabled = false;
                btnReindex.innerHTML = `<i data-lucide="refresh-cw"></i><span>Indexar Documentos</span>`;
                if (window.lucide) window.lucide.createIcons();
            }
        });
    }

    // 2. Consulta RAG (Buscador)
    const formSearch = document.getElementById("form-search");
    if (formSearch) {
        formSearch.addEventListener("submit", async (e) => {
            e.preventDefault();
            const input = document.getElementById("input-query");
            const query = input.value.trim();
            if (!query) return;
            
            // Agregar mensaje del usuario al chat
            agregarMensajeChat("user", query);
            input.value = "";
            
            // Crear mensaje temporal de carga para la IA
            const loaderId = agregarMensajeChat("assistant", "Buscando en los archivos de la comuna...", true);
            
            try {
                const res = await fetch(`${API_BASE}/api/search`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ pregunta: query })
                });
                
                if (res.ok) {
                    const data = await res.json();
                    actualizarMensajeChat(loaderId, data.respuesta, data.fuentes);
                } else {
                    actualizarMensajeChat(loaderId, "❌ Ocurrió un error al procesar la respuesta del servidor.");
                }
            } catch (e) {
                actualizarMensajeChat(loaderId, "❌ Error de conexión con el servidor de IA.");
            }
        });
    }

    // 3. (Handler de cartas removido — migrado a index.html inline con toast/showLoading)

    // 4. Registrar Actividad
    const formActivity = document.getElementById("form-activity");
    if (formActivity) {
        // Inicializar fecha de hoy en el input
        document.getElementById("act-date").value = new Date().toISOString().split('T')[0];
        
        formActivity.addEventListener("submit", async (e) => {
            e.preventDefault();
            const submitBtn = formActivity.querySelector("button[type='submit']");
            const origHTML = submitBtn.innerHTML;
            
            submitBtn.disabled = true;
            submitBtn.innerHTML = `<i data-lucide="loader" class="animate-spin"></i><span>Registrando...</span>`;
            if (window.lucide) window.lucide.createIcons();
            
            const photoInput = document.getElementById("act-photos");
            const fotosSubidas = [];
            
            // Subir fotos primero si hay seleccionadas
            if (photoInput.files.length > 0) {
                for (let i = 0; i < photoInput.files.length; i++) {
                    const formData = new FormData();
                    formData.append("file", photoInput.files[i]);
                    
                    try {
                        const fileRes = await fetch(`${API_BASE}/api/activities/upload-photo`, {
                            method: "POST",
                            body: formData
                        });
                        if (fileRes.ok) {
                            const fileData = await fileRes.json();
                            fotosSubidas.push(fileData.filepath);
                        }
                    } catch (err) {
                        console.error("Error subiendo foto:", err);
                    }
                }
            }
            
            const data = {
                fecha: document.getElementById("act-date").value,
                categoria: document.getElementById("act-category").value,
                descripcion: document.getElementById("act-desc").value,
                participantes: parseInt(document.getElementById("act-participants").value) || 0,
                fotos: fotosSubidas
            };
            
            try {
                const res = await fetch(`${API_BASE}/api/activities`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(data)
                });
                
                if (res.ok) {
                    formActivity.reset();
                    document.getElementById("act-date").value = new Date().toISOString().split('T')[0];
                    await cargarCategoriasActividades(); // Recargar por si se agregó una nueva
                    await cargarActividadesRegistradas();
                    alert("Actividad guardada exitosamente.");
                } else {
                    alert("Error al guardar la actividad.");
                }
            } catch (err) {
                alert("Error de conexión al servidor.");
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = origHTML;
                if (window.lucide) window.lucide.createIcons();
            }
        });
    }

    // 5. Compilar Informes PDF
    const btnReports = document.querySelectorAll(".btn-report");
    btnReports.forEach(btn => {
        btn.addEventListener("click", async () => {
            const period = btn.getAttribute("data-period");
            const origHTML = btn.innerHTML;
            
            btn.disabled = true;
            btn.innerHTML = `<i data-lucide="loader" class="animate-spin"></i><span>Generando PDF...</span>`;
            if (window.lucide) window.lucide.createIcons();
            
            const formData = new FormData();
            formData.append("periodo", period);
            
            try {
                const res = await fetch(`${API_BASE}/api/reports`, {
                    method: "POST",
                    body: formData
                });
                
                if (res.ok) {
                    const data = await res.json();
                    agregarReporteGeneradoListado(data);
                } else {
                    alert("Error al generar el informe.");
                }
            } catch (e) {
                alert("Error de conexión.");
            } finally {
                btn.disabled = false;
                btn.innerHTML = origHTML;
                if (window.lucide) window.lucide.createIcons();
            }
        });
    });

    // 6. Agendar Tareas y Calendario
    const formTask = document.getElementById("form-task");
    if (formTask) {
        formTask.addEventListener("submit", async (e) => {
            e.preventDefault();
            const submitBtn = formTask.querySelector("button[type='submit']");
            const origHTML = submitBtn.innerHTML;
            
            submitBtn.disabled = true;
            submitBtn.innerHTML = `<i data-lucide="loader" class="animate-spin"></i><span>Guardando...</span>`;
            if (window.lucide) window.lucide.createIcons();
            
            const rawDateTime = document.getElementById("task-date").value; // Formato YYYY-MM-DDTHH:MM
            const formattedDateTime = rawDateTime.replace("T", " "); // Cambiar a YYYY-MM-DD HH:MM
            
            const data = {
                titulo: document.getElementById("task-title").value,
                descripcion: document.getElementById("task-desc").value,
                fecha_limite: formattedDateTime,
                recordatorio_dias: parseInt(document.getElementById("task-reminder").value) || 1
            };
            
            try {
                const res = await fetch(`${API_BASE}/api/tasks`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(data)
                });
                
                if (res.ok) {
                    formTask.reset();
                    await cargarAgendaComunal();
                    alert("Tarea agendada y en cola de sincronización.");
                } else {
                    alert("Error al guardar la tarea.");
                }
            } catch (err) {
                alert("Error de conexión al servidor.");
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = origHTML;
                if (window.lucide) window.lucide.createIcons();
            }
        });
    }
}

// ============================================================
// Funciones de Dibujo del Chat (RAG)
// ============================================================
function agregarMensajeChat(sender, text, isLoader = false) {
    const container = document.getElementById("search-chat");
    const msgId = "msg-" + Date.now() + Math.random().toString(36).substr(2, 5);
    
    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message", `${sender}-message`);
    messageDiv.id = msgId;
    
    const avatarDiv = document.createElement("div");
    avatarDiv.classList.add("message-avatar");
    avatarDiv.textContent = sender === "assistant" ? "CPPO" : "Vocero";
    
    const contentDiv = document.createElement("div");
    contentDiv.classList.add("message-content");
    
    if (isLoader) {
        contentDiv.innerHTML = `<p class="loader-text"><i data-lucide="loader" class="animate-spin" style="margin-right:8px; display:inline-block; vertical-align:middle;"></i>${text}</p>`;
    } else {
        contentDiv.innerHTML = `<p>${text.replace(/\n/g, "<br>")}</p>`;
    }
    
    messageDiv.appendChild(avatarDiv);
    messageDiv.appendChild(contentDiv);
    container.appendChild(messageDiv);
    container.scrollTop = container.scrollHeight;
    
    if (window.lucide) window.lucide.createIcons();
    return msgId;
}

function actualizarMensajeChat(id, text, fuentes = []) {
    const msgDiv = document.getElementById(id);
    if (!msgDiv) return;
    
    const contentDiv = msgDiv.querySelector(".message-content");
    if (!contentDiv) return;
    
    let htmlContent = `<p>${text.replace(/\n/g, "<br>")}</p>`;
    
    if (fuentes && fuentes.length > 0) {
        htmlContent += `
        <div class="sources-container">
            <strong>Fuentes consultadas:</strong><br>
            ${fuentes.map(f => `• ${f}`).join("<br>")}
        </div>`;
    }
    
    contentDiv.innerHTML = htmlContent;
    
    const container = document.getElementById("search-chat");
    container.scrollTop = container.scrollHeight;
}

// ============================================================
// Carga y Renderizado de Listados en Tiempo Real
// ============================================================
async function cargarActividadesRegistradas() {
    const list = document.getElementById("activities-list");
    if (!list) return;
    
    try {
        const res = await fetch(`${API_BASE}/api/activities`);
        if (res.ok) {
            const actividades = await res.json();
            list.innerHTML = "";
            
            if (actividades.length === 0) {
                list.innerHTML = `<p class="empty-state">No se han registrado actividades aún.</p>`;
                return;
            }
            
            actividades.forEach(act => {
                const item = document.createElement("div");
                item.classList.add("list-item");
                
                // Procesar imágenes adjuntas
                let mediaHTML = "";
                if (act.fotos && act.fotos.length > 0) {
                    mediaHTML = `<div style="margin-top: 8px; display:flex; gap: 8px;">`;
                    act.fotos.forEach(path => {
                        const parts = path.split(/[\\/]/);
                        const fn = parts[parts.length - 1];
                        mediaHTML += `<img src="/media/${encodeURIComponent(fn)}" style="width: 50px; height: 50px; object-fit: cover; border-radius:6px; border:1px solid rgba(255,255,255,0.1)">`;
                    });
                    mediaHTML += `</div>`;
                }
                
                item.innerHTML = `
                    <div class="item-info" style="width: 100%;">
                        <h5><span class="item-badge">${escapeHTML(act.categoria)}</span> ${escapeHTML(act.fecha)}</h5>
                        <p>${escapeHTML(act.descripcion).replace(/\n/g, "<br>")}</p>
                        <p style="margin-top:4px; font-size:0.8rem; color: var(--accent);">👥 Participantes: ${act.participantes}</p>
                        ${mediaHTML}
                    </div>
                `;
                list.appendChild(item);
            });
            if (window.lucide) window.lucide.createIcons();
        }
    } catch (e) {
        console.error("Error cargando actividades:", e);
    }
}

async function cargarAgendaComunal() {
    const list = document.getElementById("tasks-list");
    if (!list) return;
    
    try {
        const res = await fetch(`${API_BASE}/api/tasks`);
        if (res.ok) {
            const tareas = await res.json();
            list.innerHTML = "";
            
            if (tareas.length === 0) {
                list.innerHTML = `<p class="empty-state">No hay tareas o alertas agendadas.</p>`;
                return;
            }
            
            tareas.forEach(t => {
                const item = document.createElement("div");
                item.classList.add("list-item");
                
                // Estilo según si está completada o no
                const inlineStyle = t.completada ? "opacity: 0.5; text-decoration: line-through;" : "";
                
                // Icono e indicación de Google Calendar
                const calendarBadge = t.sincronizado_calendar 
                    ? `<span class="item-badge" style="background: rgba(16, 185, 129, 0.1); color: var(--success); border-color: rgba(16, 185, 129, 0.3);">Google Calendar</span>` 
                    : "";
                
                const actionBtn = t.completada 
                    ? "" 
                    : `<button class="btn btn-secondary btn-sm btn-complete" data-id="${t.id}" title="Marcar como Completada">
                           <i data-lucide="check"></i>
                       </button>`;
                
                item.innerHTML = `
                    <div class="item-info" style="${inlineStyle}">
                        <h5>${escapeHTML(t.titulo)} ${calendarBadge}</h5>
                        <p><strong>Límite:</strong> ${escapeHTML(t.fecha_limite)} | ${escapeHTML(t.descripcion) || 'Sin detalles'}</p>
                    </div>
                    <div class="item-actions">
                        ${actionBtn}
                    </div>
                `;
                list.appendChild(item);
            });
            
            // Vincular botones de completar
            const compButtons = list.querySelectorAll(".btn-complete");
            compButtons.forEach(btn => {
                btn.addEventListener("click", async () => {
                    const id = btn.getAttribute("data-id");
                    try {
                        const completeRes = await fetch(`${API_BASE}/api/tasks/${id}/complete`, { method: "PUT" });
                        if (completeRes.ok) {
                            await cargarAgendaComunal();
                        }
                    } catch (e) {
                        console.error("Error al completar tarea:", e);
                    }
                });
            });
            
            if (window.lucide) window.lucide.createIcons();
        }
    } catch (e) {
        console.error("Error cargando agenda:", e);
    }
}

// ============================================================
// Historial de Informes Generados
// ============================================================
function agregarReporteGeneradoListado(reporte) {
    const container = document.getElementById("report-output-container");
    const empty = container.querySelector(".empty-state");
    if (empty) {
        container.innerHTML = "";
    }
    
    const downloadUrl = `/informes/${reporte.nombre_archivo}`;
    
    const item = document.createElement("div");
    item.classList.add("report-download-item");
    item.innerHTML = `
        <div class="item-info">
            <h5>Informe de Gestión ${reporte.tipo}</h5>
            <p><strong>Actividades:</strong> ${reporte.total_actividades} | <strong>Participantes:</strong> ${reporte.total_participantes}</p>
        </div>
        <div class="item-actions">
            <a href="${downloadUrl}" target="_blank" class="btn btn-primary" title="Descargar PDF">
                <i data-lucide="download"></i>
                <span>Descargar PDF</span>
            </a>
        </div>
    `;
    
    container.insertBefore(item, container.firstChild);
    if (window.lucide) window.lucide.createIcons();
}
