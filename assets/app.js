document.addEventListener('DOMContentLoaded', () => {
    // --- Elements ---
    const urlInput = document.getElementById('urlInput');
    const previewContainer = document.getElementById('previewContainer');
    const previewThumb = document.getElementById('previewThumb');
    const previewId = document.getElementById('previewId');
    const addToQueueBtn = document.getElementById('addToQueueBtn');

    // Options
    const formatSelect = document.getElementById('formatSelect');
    const qualitySelect = document.getElementById('qualitySelect');

    // Sections
    const activeSection = document.getElementById('activeDownloadSection');
    const activeThumb = document.getElementById('activeThumb');
    const activeTitle = document.getElementById('activeTitle');
    const activeMeta = document.getElementById('activeMeta');
    const progressBar = document.getElementById('progressBar');
    const statusText = document.getElementById('statusText');
    const cancelBtn = document.getElementById('cancelBtn');

    const queueList = document.getElementById('queueList');
    const queueCount = document.getElementById('queueCount');
    const historyList = document.getElementById('historyList');

    // --- State ---
    let currentPreviewUrl = '';
    let currentVideoId = '';

    // --- Logic: Options Dynamic ---
    formatSelect.addEventListener('change', () => {
        const isAudio = formatSelect.value === 'audio';
        qualitySelect.innerHTML = '';

        if (isAudio) {
            qualitySelect.innerHTML = `
                <option value="0">Mejor (320kbps)</option>
                <option value="5">Alta (192kbps)</option>
                <option value="9">Media (128kbps)</option>
            `;
        } else {
            qualitySelect.innerHTML = `
                <option value="best">Mejor Disponible</option>
                <option value="2160">4K (2160p)</option>
                <option value="1440">2K (1440p)</option>
                <option value="1080">1080p</option>
                <option value="720">720p</option>
                <option value="480">480p</option>
            `;
        }
    });

    // --- Logic: Preview ---
    urlInput.addEventListener('input', () => {
        const url = urlInput.value.trim();
        const id = extractVideoID(url);

        if (id && id !== currentVideoId) {
            currentVideoId = id;
            currentPreviewUrl = `https://img.youtube.com/vi/${id}/mqdefault.jpg`;

            previewThumb.src = currentPreviewUrl;
            previewId.innerText = `ID: ${id}`;
            previewContainer.style.display = 'flex';
        } else if (!id) {
            currentVideoId = '';
            previewContainer.style.display = 'none';
        }
    });

    function extractVideoID(url) {
        if (!url) return null;
        const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
        const match = url.match(regExp);
        return (match && match[2].length === 11) ? match[2] : null;
    }

    // --- Logic: Add to Queue ---
    addToQueueBtn.addEventListener('click', async () => {
        if (!currentVideoId) return;

        addToQueueBtn.disabled = true;
        addToQueueBtn.innerText = 'Añadiendo...';

        const format = formatSelect.value;
        const quality = qualitySelect.value;

        try {
            const res = await fetch('/api/queue', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: urlInput.value.trim(),
                    title: `Video ${currentVideoId}`,
                    thumbnail: currentPreviewUrl,
                    format_type: format,
                    quality: quality
                })
            });

            if (res.ok) {
                urlInput.value = '';
                previewContainer.style.display = 'none';
                currentVideoId = '';
                updateState();
            } else {
                alert('Error al añadir a la cola');
            }
        } catch (e) {
            console.error(e);
        } finally {
            addToQueueBtn.disabled = false;
            addToQueueBtn.innerText = 'Añadir a Cola';
        }
    });

    // --- Logic: Cancel ---
    cancelBtn.addEventListener('click', async () => {
        if (confirm('¿Seguro que quieres cancelar la descarga actual?')) {
            await fetch('/api/cancel', { method: 'POST' });
        }
    });

    // --- Logic: Polling Loop ---
    async function updateState() {
        try {
            const res = await fetch('/api/state');
            if (!res.ok) return;
            const state = await res.json();
            render(state);
        } catch (e) {
            // console.error("Error polling", e);
        }
    }

    function render(state) {
        // 1. Render Active
        if (state.current_task) {
            activeSection.style.display = 'block';
            if (state.current_task.thumbnail) {
                activeThumb.src = state.current_task.thumbnail;
            } else {
                activeThumb.src = 'assets/default_thumb.png'; // Fallback old icon
            }
            activeTitle.innerText = state.current_task.title;
            const task = state.current_task;
            activeMeta.innerText = `${task.format_type.toUpperCase()} - ${task.quality === '0' ? 'HQ' : task.quality}`;

            const progress = task.progress || 0;
            progressBar.style.width = `${progress}%`;
            statusText.innerText = `${progress.toFixed(1)}%`;
        } else {
            activeSection.style.display = 'none';
        }

        // 2. Render Queue
        queueCount.innerText = state.queue.length;
        if (state.queue.length === 0) {
            queueList.innerHTML = '<div style="text-align:center; color:#444; padding:1rem;">Cola vacía</div>';
        } else {
            queueList.innerHTML = state.queue.map(task => `
                <div class="task-item">
                    <img src="${task.thumbnail}" class="task-thumb">
                    <div class="task-details">
                        <div class="task-title">PENDIENTE: ${task.url}</div>
                        <div class="task-meta">${task.format_type.toUpperCase()} | Esperando...</div>
                    </div>
                    <button class="delete-btn" onclick="removeFromQueue('${task.id}')">&times;</button>
                </div>
            `).join('');
        }

        // 3. Render History (Rich UI)
        if (state.history.length === 0) {
            historyList.innerHTML = '';
        } else {
            historyList.innerHTML = state.history.map(file => {
                const isAudio = file.format_type === 'audio';
                const typeIcon = isAudio ? '🎵' : '🎬';
                // Badge de calidad
                const qualityBadge = file.quality_str
                    ? `<span style="background:${isAudio ? '#e91e63' : '#2196F3'}; border-radius:4px; padding:2px 5px; font-size:0.7em; margin-left:6px; vertical-align:middle; color:white;">${file.quality_str}</span>`
                    : '';
                // Fallback thumbnail
                const thumbSrc = file.thumbnail || 'assets/default_thumb.png'; // Fallback old icon

                return `
                <div class="task-item" style="border-left: 3px solid ${isAudio ? '#e91e63' : '#2196F3'};">
                    <div style="position:relative; width:48px; height:48px; flex-shrink:0;">
                        <img src="${thumbSrc}" class="task-thumb" style="width:100%; height:100%; object-fit:cover;">
                        <div style="position:absolute; bottom:0; right:0; background:rgba(0,0,0,0.6); color:white; padding:0 3px; font-size:0.7em;">${typeIcon}</div>
                    </div>
                    <div class="task-details">
                        <div class="task-title" title="${file.filename}">
                            ${file.filename}
                        </div>
                        <div class="task-meta">
                            <span style="opacity:0.8; font-size:0.9em;">Completado</span>
                            ${qualityBadge}
                            <span style="opacity:0.6; font-size:0.8em; margin-left:5px;">${file.mtime ? new Date(file.mtime * 1000).toLocaleTimeString() : ''}</span>
                        </div>
                    </div>
                    <a href="/downloads/${encodeURIComponent(file.filename)}" class="download-link-btn" download>Guardar</a>
                </div>
            `}).join('');
        }
    }

    window.removeFromQueue = async (id) => {
        await fetch(`/api/queue/${id}`, { method: 'DELETE' });
        updateState();
    };

    setInterval(updateState, 1000);
    updateState();
});
