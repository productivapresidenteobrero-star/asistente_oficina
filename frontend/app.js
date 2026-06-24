// ============================================================
// Asistente Comunal — app.js
// Compatible con el nuevo diseño Tailwind Material 3
// ============================================================

const API_BASE = "";

function escapeHTML(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function showToast(message, type = 'success') {
    const existing = document.getElementById('app-toast');
    if (existing) existing.remove();

    const colors = {
        success: 'bg-emerald-500',
        error:   'bg-error',
        info:    'bg-primary'
    };

    const toast = document.createElement('div');
    toast.id = 'app-toast';
    toast.className = `fixed top-4 right-4 z-[100] flex items-center gap-sm px-lg py-md rounded-xl shadow-xl text-white text-body-sm font-bold transition-all duration-300 ${colors[type] || colors.info}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// ============================================================
// Navegación de Pestañas (SPA)
// ============================================================
function setupTabs() {
    const navItems = document.querySelectorAll("[data-tab]");
    const tabPanes = document.querySelectorAll(".tab-pane");

    // Función de activación
    function activateTab(tabId) {
        navItems.forEach(nav => {
            const isActive = nav.getAttribute('data-tab') === tabId;
            // Clases de estado activo vs inactivo para sidebar links
            if (nav.closest('aside')) {
                nav.classList.toggle('bg-primary-container', isActive);
                nav.classList.toggle('text-on-primary-container', isActive);
                nav.classList.toggle('font-bold', isActive);
                nav.classList.toggle('shadow-lg', isActive);
                nav.classList.toggle('text-on-surface-variant', !isActive);
                nav.classList.toggle('hover:bg-surface-container-low', !isActive);
            }
            // Bottom nav mobile
            if (nav.closest('nav')) {
                const icon = nav.querySelector('.material-symbols-outlined');
                if (isActive) {
                    nav.classList.add('bg-primary', 'text-on-primary', 'rounded-full', 'px-6', 'py-2', 'shadow-md');
                    nav.classList.remove('text-on-surface-variant', 'px-4', 'py-1');
                    if (icon) icon.style.fontVariationSettings = "'FILL' 1, 'wght' 600";
                } else {
                    nav.classList.remove('bg-primary', 'text-on-primary', 'rounded-full', 'px-6', 'py-2', 'shadow-md');
                    nav.classList.add('text-on-surface-variant', 'px-4', 'py-1');
                    if (icon) icon.style.fontVariationSettings = "'FILL' 0, 'wght' 400";
                }
            }
        });

        tabPanes.forEach(pane => {
            pane.classList.toggle('active', pane.id === `tab-${tabId}`);
        });

        // Actualizar título del header móvil
        const mobileHeader = document.querySelector('header .text-headline-md');
        if (mobileHeader) {
            const labels = {
                dashboard: 'Inicio',
                padron:    'Voceros',
                consultas: 'Consultas',
                archivos:  'Archivos',
                actividades: 'Actividades',
                cartas:    'Cartas',
                tareas:    'Agenda',
                bitacora:  'Bitácora',
                informes:  'Informes'
            };
            mobileHeader.textContent = labels[tabId] || 'Inicio';
        }

        // Re-cargar datos según la sección
        if (tabId === 'actividades') cargarActividadesRegistradas();
        if (tabId === 'tareas') cargarAgendaComunal();
        if (tabId === 'dashboard') cargarDashboardStats();
    }

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const targetTab = item.getAttribute('data-tab');
            if (targetTab) activateTab(targetTab);
        });
    });

    // Activar Dashboard por defecto
    activateTab('dashboard');
}

// ============================================================
// Dashboard — Carga de Estadísticas
// ============================================================
async function cargarDashboardStats() {
    try {
        const res = await fetch(`${API_BASE}/api/dashboard/stats`);
        if (!res.ok) return;
        const data = await res.json();

        // Cards de métricas
        const activEl = document.getElementById('stat-actividades');
        const partEl  = document.getElementById('stat-participantes');
        const cartEl  = document.getElementById('stat-cartas');
        const pendEl  = document.getElementById('stat-pendientes');

        if (activEl) activEl.textContent = data.total_actividades ?? 0;
        if (partEl)  partEl.textContent  = data.total_participantes ?? 0;
        if (cartEl)  cartEl.textContent  = data.cartas_emitidas ?? 0;
        if (pendEl)  pendEl.textContent  = data.tareas_pendientes ?? 0;

        // Próximas tareas en el Dashboard
        await cargarProximasTareasDash();
    } catch (e) {
        console.error('Error cargando stats del dashboard:', e);
    }
}

async function cargarProximasTareasDash() {
    const container = document.getElementById('dash-proximas-tareas');
    if (!container) return;

    try {
        const res = await fetch(`${API_BASE}/api/tasks`);
        if (!res.ok) return;
        const tareas = await res.json();
        const pendientes = tareas.filter(t => !t.completada).slice(0, 3);

        if (pendientes.length === 0) {
            container.innerHTML = `
                <div class="py-xl flex flex-col items-center">
                    <span class="material-symbols-outlined text-[64px] text-primary opacity-10" style="font-variation-settings:'wght' 200">calendar_today</span>
                    <p class="text-on-surface-variant font-body-sm mt-md">Tu agenda está despejada.</p>
                </div>`;
            return;
        }

        container.innerHTML = pendientes.map(t => `
            <div class="flex items-start gap-md py-md border-b border-outline-variant last:border-0">
                <div class="w-8 h-8 rounded-lg bg-primary-container/30 flex items-center justify-center flex-shrink-0">
                    <span class="material-symbols-outlined text-primary text-[16px]">event</span>
                </div>
                <div class="flex-1">
                    <p class="text-body-sm font-bold text-on-surface">${escapeHTML(t.titulo)}</p>
                    <p class="text-[11px] text-on-surface-variant mt-1">${escapeHTML(t.fecha_limite)}</p>
                </div>
            </div>
        `).join('');
    } catch (e) {
        console.error('Error cargando tareas para dashboard:', e);
    }
}

// ============================================================
// Padrón de Voceros — Búsqueda
// ============================================================
function setupPadronSearch() {
    const input = document.getElementById('padron-search-input');
    if (!input) return;

    input.addEventListener('input', async () => {
        const q = input.value.trim();
        await cargarVoceros(q);
    });

    const filterBtns = document.querySelectorAll('.filter-unidad-btn');
    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => {
                b.classList.remove('bg-primary', 'text-on-primary');
                b.classList.add('bg-surface-container-high', 'text-on-surface-variant');
            });
            btn.classList.add('bg-primary', 'text-on-primary');
            btn.classList.remove('bg-surface-container-high', 'text-on-surface-variant');
            cargarVoceros(input.value.trim(), btn.getAttribute('data-unidad') || '');
        });
    });
}

async function cargarVoceros(q = '', unidad = '') {
    const list = document.getElementById('voceros-list');
    if (!list) return;

    list.innerHTML = `<div class="flex justify-center py-xl"><span class="material-symbols-outlined text-primary animate-spin">progress_activity</span></div>`;

    try {
        const params = new URLSearchParams();
        if (q) params.set('q', q);
        if (unidad && unidad !== 'Todos') params.set('unidad', unidad);

        const res = await fetch(`${API_BASE}/api/voceros?${params.toString()}`);
        if (!res.ok) {
            list.innerHTML = `<p class="text-on-surface-variant text-center py-xl">Error al cargar voceros.</p>`;
            return;
        }
        const voceros = await res.json();

        if (voceros.length === 0) {
            list.innerHTML = `
                <div class="flex flex-col items-center py-xl text-center">
                    <span class="material-symbols-outlined text-[48px] text-primary opacity-20">person_search</span>
                    <p class="text-on-surface-variant font-body-sm mt-md">No se encontraron voceros con ese criterio.</p>
                </div>`;
            return;
        }

        list.innerHTML = voceros.map(v => `
            <div class="flex flex-col lg:flex-row lg:items-center justify-between p-lg tonal-surface ghost-border rounded-xl hover:border-primary/40 transition-all duration-200 group">
                <div class="flex items-center gap-lg">
                    <div class="relative">
                        <div class="w-12 h-12 rounded-full bg-primary-container flex items-center justify-center text-on-primary-container font-bold text-body-lg flex-shrink-0">
                            ${escapeHTML(v.nombre ? v.nombre.charAt(0).toUpperCase() : '?')}
                        </div>
                    </div>
                    <div>
                        <h3 class="text-body-md font-bold text-on-surface group-hover:text-primary transition-colors">${escapeHTML(v.nombre)}</h3>
                        <p class="text-body-sm text-on-surface-variant">C.I. ${escapeHTML(v.cedula)} • ${escapeHTML(v.unidad || 'Sin unidad')}</p>
                    </div>
                </div>
                <div class="mt-md lg:mt-0 flex items-center gap-sm">
                    ${v.telefono ? `<a href="tel:${escapeHTML(v.telefono)}" class="w-10 h-10 flex items-center justify-center rounded-xl ghost-border text-on-surface-variant hover:bg-surface-container-high transition-all">
                        <span class="material-symbols-outlined text-[20px]">call</span>
                    </a>` : ''}
                    <button onclick="verDetalleVocero(${v.id})" class="flex items-center gap-xs px-md py-sm rounded-lg bg-primary-container/20 text-primary text-label-md font-label-md hover:bg-primary-container/40 transition-colors">
                        <span class="material-symbols-outlined text-[16px]">info</span>
                        Detalle
                    </button>
                </div>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = `<p class="text-on-surface-variant text-center py-xl">Error de conexión.</p>`;
        console.error(e);
    }
}

// ============================================================
// Actividades — Formulario y Listado
// ============================================================
async function cargarCategoriasActividades() {
    const select = document.getElementById('act-category');
    if (!select) return;

    try {
        const res = await fetch(`${API_BASE}/api/activities/categories`);
        if (res.ok) {
            const categorias = await res.json();
            select.innerHTML = categorias.map(cat =>
                `<option value="${escapeHTML(cat)}">${escapeHTML(cat)}</option>`
            ).join('');
        }
    } catch (e) {
        console.error('Error cargando categorías:', e);
    }
}

async function cargarActividadesRegistradas() {
    const list = document.getElementById('activities-list');
    if (!list) return;

    list.innerHTML = `<div class="flex justify-center py-xl"><span class="material-symbols-outlined text-primary animate-spin">progress_activity</span></div>`;

    try {
        const res = await fetch(`${API_BASE}/api/activities`);
        if (!res.ok) { list.innerHTML = '<p class="text-center text-on-surface-variant py-xl">Error al cargar actividades.</p>'; return; }
        const actividades = await res.json();

        if (actividades.length === 0) {
            list.innerHTML = `
                <div class="flex flex-col items-center py-xl text-center">
                    <span class="material-symbols-outlined text-[48px] text-primary opacity-20">event_note</span>
                    <p class="text-on-surface-variant font-body-sm mt-md">No se han registrado actividades aún.</p>
                </div>`;
            return;
        }

        list.innerHTML = actividades.map(act => {
            let mediaHTML = '';
            if (act.fotos && act.fotos.length > 0) {
                mediaHTML = `<div class="flex gap-sm mt-md flex-wrap">` +
                    act.fotos.map(path => {
                        const fn = path.split(/[\\\/]/).pop();
                        return `<img src="/media/${encodeURIComponent(fn)}" class="w-16 h-16 object-cover rounded-lg border border-outline-variant">`;
                    }).join('') +
                    `</div>`;
            }
            return `
                <div class="tonal-surface ghost-border rounded-xl p-lg flex flex-col gap-sm">
                    <div class="flex items-center justify-between">
                        <span class="text-label-md bg-primary-container/30 text-primary px-md py-xs rounded-full font-label-md">${escapeHTML(act.categoria)}</span>
                        <span class="text-[11px] text-on-surface-variant">${escapeHTML(act.fecha)}</span>
                    </div>
                    <p class="text-body-sm text-on-surface">${escapeHTML(act.descripcion).replace(/\n/g, '<br>')}</p>
                    <p class="text-[12px] text-primary font-bold flex items-center gap-xs">
                        <span class="material-symbols-outlined text-[16px]">group</span>
                        ${act.participantes} participantes
                    </p>
                    ${mediaHTML}
                </div>`;
        }).join('');
    } catch (e) {
        console.error('Error cargando actividades:', e);
        list.innerHTML = '<p class="text-center text-on-surface-variant py-xl">Error de conexión.</p>';
    }
}

// ============================================================
// Tareas y Agenda
// ============================================================
async function cargarAgendaComunal() {
    const list = document.getElementById('tasks-list');
    if (!list) return;

    list.innerHTML = `<div class="flex justify-center py-xl"><span class="material-symbols-outlined text-primary animate-spin">progress_activity</span></div>`;

    try {
        const res = await fetch(`${API_BASE}/api/tasks`);
        if (!res.ok) return;
        const tareas = await res.json();

        if (tareas.length === 0) {
            list.innerHTML = `
                <div class="flex flex-col items-center py-xl text-center">
                    <span class="material-symbols-outlined text-[48px] text-primary opacity-20">calendar_today</span>
                    <p class="text-on-surface-variant font-body-sm mt-md">No hay tareas agendadas.</p>
                </div>`;
            return;
        }

        list.innerHTML = tareas.map(t => `
            <div class="tonal-surface ghost-border rounded-xl p-lg flex items-start gap-md ${t.completada ? 'opacity-50' : ''}">
                <div class="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${t.completada ? 'bg-emerald-100' : 'bg-primary-container/20'}">
                    <span class="material-symbols-outlined ${t.completada ? 'text-emerald-600' : 'text-primary'}" style="font-variation-settings: 'FILL' ${t.completada ? 1 : 0}">
                        ${t.completada ? 'task_alt' : 'event'}
                    </span>
                </div>
                <div class="flex-1">
                    <p class="text-body-sm font-bold text-on-surface ${t.completada ? 'line-through' : ''}">${escapeHTML(t.titulo)}</p>
                    <p class="text-[11px] text-on-surface-variant mt-xs">${escapeHTML(t.fecha_limite)}</p>
                    ${t.descripcion ? `<p class="text-[12px] text-on-surface-variant mt-xs">${escapeHTML(t.descripcion)}</p>` : ''}
                </div>
                ${!t.completada ? `
                <button onclick="completarTarea(${t.id}, this)" class="flex-shrink-0 w-9 h-9 rounded-lg border border-outline-variant text-on-surface-variant hover:bg-emerald-100 hover:text-emerald-600 hover:border-emerald-300 transition-all flex items-center justify-center">
                    <span class="material-symbols-outlined text-[18px]">check</span>
                </button>` : ''}
            </div>
        `).join('');
    } catch (e) {
        console.error('Error cargando agenda:', e);
    }
}

async function completarTarea(id, btn) {
    btn.disabled = true;
    try {
        const res = await fetch(`${API_BASE}/api/tasks/${id}/complete`, { method: 'PUT' });
        if (res.ok) {
            showToast('Tarea marcada como completada ✓', 'success');
            await cargarAgendaComunal();
        } else {
            showToast('Error al completar la tarea', 'error');
        }
    } catch (e) {
        showToast('Error de conexión', 'error');
    }
}

// ============================================================
// Chat RAG (Buscador de Archivos)
// ============================================================
let chatMsgCounter = 0;

function agregarMensajeChat(sender, text, isLoader = false) {
    const container = document.getElementById('search-chat');
    if (!container) return null;
    const msgId = `chat-msg-${++chatMsgCounter}`;

    const isUser = sender === 'user';
    const div = document.createElement('div');
    div.id = msgId;
    div.className = `flex gap-sm ${isUser ? 'justify-end' : 'justify-start'}`;

    if (isLoader) {
        div.innerHTML = `
            <div class="flex items-center gap-sm bg-surface-container rounded-xl px-md py-sm">
                <span class="material-symbols-outlined text-primary text-[18px] animate-spin">progress_activity</span>
                <span class="text-body-sm text-on-surface-variant">${escapeHTML(text)}</span>
            </div>`;
    } else if (isUser) {
        div.innerHTML = `
            <div class="bg-primary text-on-primary rounded-xl rounded-tr-sm px-lg py-md max-w-[80%]">
                <p class="text-body-sm">${escapeHTML(text).replace(/\n/g, '<br>')}</p>
            </div>`;
    } else {
        div.innerHTML = `
            <div class="flex gap-sm items-start max-w-[85%]">
                <div class="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center flex-shrink-0 text-[10px] font-bold text-on-primary-container">IA</div>
                <div class="bg-surface-container-low ghost-border rounded-xl rounded-tl-sm px-lg py-md">
                    <p class="text-body-sm text-on-surface">${escapeHTML(text).replace(/\n/g, '<br>')}</p>
                </div>
            </div>`;
    }

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return msgId;
}

function actualizarMensajeChat(id, text, fuentes = []) {
    const msgDiv = document.getElementById(id);
    if (!msgDiv) return;

    let sourcesHTML = '';
    if (fuentes && fuentes.length > 0) {
        sourcesHTML = `<div class="mt-sm pt-sm border-t border-outline-variant">
            <p class="text-[11px] text-on-surface-variant font-bold mb-xs">Fuentes:</p>
            ${fuentes.map(f => `<p class="text-[11px] text-on-surface-variant">• ${escapeHTML(f)}</p>`).join('')}
        </div>`;
    }

    msgDiv.innerHTML = `
        <div class="flex gap-sm items-start max-w-[85%]">
            <div class="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center flex-shrink-0 text-[10px] font-bold text-on-primary-container">IA</div>
            <div class="bg-surface-container-low ghost-border rounded-xl rounded-tl-sm px-lg py-md">
                <p class="text-body-sm text-on-surface">${escapeHTML(text).replace(/\n/g, '<br>')}</p>
                ${sourcesHTML}
            </div>
        </div>`;

    const container = document.getElementById('search-chat');
    if (container) container.scrollTop = container.scrollHeight;
}

// ============================================================
// Informes PDF
// ============================================================
function agregarReporteGeneradoListado(reporte) {
    const container = document.getElementById('report-output-container');
    if (!container) return;

    const empty = container.querySelector('.empty-report-state');
    if (empty) container.innerHTML = '';

    const downloadUrl = `/informes/${reporte.nombre_archivo}`;
    const item = document.createElement('div');
    item.className = 'tonal-surface ghost-border rounded-xl p-lg flex items-center justify-between gap-md';
    item.innerHTML = `
        <div>
            <p class="text-body-sm font-bold text-on-surface">Informe ${escapeHTML(reporte.tipo)}</p>
            <p class="text-[11px] text-on-surface-variant mt-xs">
                <span class="font-bold">${reporte.total_actividades}</span> actividades · 
                <span class="font-bold">${reporte.total_participantes}</span> participantes
            </p>
        </div>
        <a href="${downloadUrl}" target="_blank"
           class="flex items-center gap-xs px-lg py-md rounded-lg bg-primary text-on-primary text-label-md font-bold hover:opacity-90 transition-all">
            <span class="material-symbols-outlined text-[16px]">download</span>
            Descargar
        </a>`;

    container.insertBefore(item, container.firstChild);
}

// ============================================================
// Configuración de todos los formularios
// ============================================================
function setupFormularios() {
    // 1. Indexar documentos
    const btnReindex = document.getElementById('btn-reindex');
    if (btnReindex) {
        btnReindex.addEventListener('click', async () => {
            btnReindex.disabled = true;
            btnReindex.innerHTML = '<span class="material-symbols-outlined text-[18px] animate-spin">progress_activity</span><span>Indexando...</span>';
            try {
                const res = await fetch(`${API_BASE}/api/documents/index`, { method: 'POST' });
                if (res.ok) {
                    showToast('Indexación iniciada en segundo plano', 'success');
                } else {
                    showToast('Error al iniciar indexación', 'error');
                }
            } catch (e) {
                showToast('Error de conexión', 'error');
            } finally {
                btnReindex.disabled = false;
                btnReindex.innerHTML = '<span class="material-symbols-outlined text-[18px]">sync</span><span>Indexar Documentos</span>';
            }
        });
    }

    // 2. Consulta RAG
    const formSearch = document.getElementById('form-search');
    if (formSearch) {
        formSearch.addEventListener('submit', async (e) => {
            e.preventDefault();
            const input = document.getElementById('input-query');
            const query = input.value.trim();
            if (!query) return;

            agregarMensajeChat('user', query);
            input.value = '';

            const loaderId = agregarMensajeChat('assistant', 'Buscando en los archivos de la comuna...', true);

            try {
                const res = await fetch(`${API_BASE}/api/search`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pregunta: query })
                });
                if (res.ok) {
                    const data = await res.json();
                    actualizarMensajeChat(loaderId, data.respuesta, data.fuentes);
                } else {
                    actualizarMensajeChat(loaderId, '❌ Error al procesar la respuesta del servidor.');
                }
            } catch (e) {
                actualizarMensajeChat(loaderId, '❌ Error de conexión con el servidor.');
            }
        });
    }

    // 3. Registrar Actividad
    const formActivity = document.getElementById('form-activity');
    if (formActivity) {
        const dateInput = document.getElementById('act-date');
        if (dateInput) dateInput.value = new Date().toISOString().split('T')[0];

        formActivity.addEventListener('submit', async (e) => {
            e.preventDefault();
            const submitBtn = formActivity.querySelector('button[type="submit"]');
            const origHTML = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="material-symbols-outlined text-[18px] animate-spin">progress_activity</span><span>Registrando...</span>';

            const photoInput = document.getElementById('act-photos');
            const fotosSubidas = [];

            if (photoInput && photoInput.files.length > 0) {
                for (let i = 0; i < photoInput.files.length; i++) {
                    const formData = new FormData();
                    formData.append('file', photoInput.files[i]);
                    try {
                        const fileRes = await fetch(`${API_BASE}/api/activities/upload-photo`, { method: 'POST', body: formData });
                        if (fileRes.ok) {
                            const fileData = await fileRes.json();
                            fotosSubidas.push(fileData.filepath);
                        }
                    } catch (err) {
                        console.error('Error subiendo foto:', err);
                    }
                }
            }

            const data = {
                fecha: document.getElementById('act-date').value,
                categoria: document.getElementById('act-category').value,
                descripcion: document.getElementById('act-desc').value,
                participantes: parseInt(document.getElementById('act-participants').value) || 0,
                fotos: fotosSubidas
            };

            try {
                const res = await fetch(`${API_BASE}/api/activities`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (res.ok) {
                    formActivity.reset();
                    if (dateInput) dateInput.value = new Date().toISOString().split('T')[0];
                    await cargarCategoriasActividades();
                    await cargarActividadesRegistradas();
                    showToast('Actividad registrada exitosamente ✓', 'success');
                } else {
                    showToast('Error al guardar la actividad', 'error');
                }
            } catch (err) {
                showToast('Error de conexión', 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = origHTML;
            }
        });
    }

    // 4. Agendar Tarea
    const formTask = document.getElementById('form-task');
    if (formTask) {
        formTask.addEventListener('submit', async (e) => {
            e.preventDefault();
            const submitBtn = formTask.querySelector('button[type="submit"]');
            const origHTML = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="material-symbols-outlined text-[18px] animate-spin">progress_activity</span><span>Guardando...</span>';

            const rawDateTime = document.getElementById('task-date').value;
            const formattedDateTime = rawDateTime.replace('T', ' ');

            const data = {
                titulo: document.getElementById('task-title').value,
                descripcion: document.getElementById('task-desc').value || '',
                fecha_limite: formattedDateTime,
                recordatorio_dias: parseInt(document.getElementById('task-reminder').value) || 1
            };

            try {
                const res = await fetch(`${API_BASE}/api/tasks`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (res.ok) {
                    formTask.reset();
                    await cargarAgendaComunal();
                    showToast('Tarea agendada exitosamente ✓', 'success');
                } else {
                    showToast('Error al guardar la tarea', 'error');
                }
            } catch (err) {
                showToast('Error de conexión', 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = origHTML;
            }
        });
    }

    // 5. Generación de informes PDF
    document.querySelectorAll('.btn-report').forEach(btn => {
        btn.addEventListener('click', async () => {
            const period = btn.getAttribute('data-period');
            const origHTML = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<span class="material-symbols-outlined text-[18px] animate-spin">progress_activity</span><span>Generando PDF...</span>';

            const formData = new FormData();
            formData.append('periodo', period);

            try {
                const res = await fetch(`${API_BASE}/api/reports`, { method: 'POST', body: formData });
                if (res.ok) {
                    const data = await res.json();
                    agregarReporteGeneradoListado(data);
                    showToast('Informe generado exitosamente', 'success');
                } else {
                    showToast('Error al generar el informe', 'error');
                }
            } catch (e) {
                showToast('Error de conexión', 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = origHTML;
            }
        });
    });

    // 6. Cartas — Generador
    const formCartas = document.getElementById('form-carta');
    if (formCartas) {
        cargarTiposCartas();
        formCartas.addEventListener('submit', async (e) => {
            e.preventDefault();
            const submitBtn = formCartas.querySelector('button[type="submit"]');
            const origHTML = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="material-symbols-outlined text-[18px] animate-spin">progress_activity</span><span>Generando Carta...</span>';

            const data = {
                tipo: document.getElementById('carta-tipo').value,
                destinatario: document.getElementById('carta-destinatario').value,
                asunto: document.getElementById('carta-asunto').value,
                cuerpo: document.getElementById('carta-cuerpo').value,
                numero: document.getElementById('carta-numero').value || ''
            };

            try {
                const res = await fetch(`${API_BASE}/api/letters`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (res.ok) {
                    const result = await res.json();
                    mostrarCartaGenerada(result);
                    showToast('Carta generada exitosamente ✓', 'success');
                } else {
                    showToast('Error al generar la carta', 'error');
                }
            } catch (err) {
                showToast('Error de conexión', 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = origHTML;
            }
        });
    }
}

// ============================================================
// Cartas / Oficios
// ============================================================
async function cargarTiposCartas() {
    const select = document.getElementById('carta-tipo');
    if (!select) return;
    try {
        const res = await fetch(`${API_BASE}/api/letters/types`);
        if (res.ok) {
            const tipos = await res.json();
            select.innerHTML = tipos.map(t =>
                `<option value="${escapeHTML(t.id || t)}">${escapeHTML(t.nombre || t)}</option>`
            ).join('');
        }
    } catch (e) {
        console.error('Error cargando tipos de cartas:', e);
    }
}

function mostrarCartaGenerada(carta) {
    const container = document.getElementById('carta-output');
    if (!container) return;
    container.classList.remove('hidden');

    const downloadUrl = carta.ruta ? `/cartas/${carta.ruta.split(/[\\/]/).pop()}` : '#';
    container.innerHTML = `
        <div class="tonal-surface ghost-border rounded-xl p-lg">
            <div class="flex items-center gap-md mb-lg">
                <div class="w-10 h-10 rounded-xl bg-emerald-100 flex items-center justify-center">
                    <span class="material-symbols-outlined text-emerald-600" style="font-variation-settings: 'FILL' 1">task_alt</span>
                </div>
                <div>
                    <p class="text-body-sm font-bold text-on-surface">${escapeHTML(carta.tipo || 'Carta')}</p>
                    <p class="text-[11px] text-on-surface-variant">Generada exitosamente</p>
                </div>
            </div>
            ${carta.preview ? `<pre class="text-[12px] text-on-surface bg-surface-container-low rounded-lg p-md overflow-x-auto whitespace-pre-wrap mb-lg">${escapeHTML(carta.preview)}</pre>` : ''}
            <a href="${downloadUrl}" target="_blank"
               class="flex items-center justify-center gap-sm w-full py-md rounded-lg bg-primary text-on-primary font-bold text-body-sm hover:opacity-90 transition-all">
                <span class="material-symbols-outlined text-[18px]">download</span>
                Descargar PDF
            </a>
        </div>`;
}

// ============================================================
// Inicialización Principal
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    cargarCategoriasActividades();
    setupFormularios();
    setupPadronSearch();

    // Fade-in suave al cargar
    document.body.style.opacity = '0';
    setTimeout(() => {
        document.body.style.transition = 'opacity 0.4s ease';
        document.body.style.opacity = '1';
    }, 50);
});
