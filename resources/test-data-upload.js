// Stage a ZIP without sending the entire file in one HTTP request.
async function stageTestArchive(file, url, csrf, signal, showProgress) {
    const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));
    async function request(url, body) {
        const options = {signal, credentials: 'same-origin', cache: 'no-store'};
        if (body) Object.assign(options, {method: 'POST', headers: {'X-CSRFToken': csrf}, body});
        for (let attempt = 0; ; attempt++) {
            let response;
            try {
                response = await fetch(url, options);
            } catch (error) {
                if (signal.aborted || attempt >= 2) throw error;
            }
            if (response && response.ok) return response.json();
            if (response && (response.status < 500 || attempt >= 2)) {
                const result = await response.json().catch(() => ({}));
                throw new Error(result.state || 'unavailable');
            }
            await wait(500 * (attempt + 1));
        }
    }

    const start = await request(url, new URLSearchParams({name: file.name, size: String(file.size)}));
    let offset = 0;
    while (offset < file.size) {
        const chunk = new FormData();
        chunk.set('offset', String(offset));
        chunk.set('chunk', file.slice(offset, offset + start.chunk_size), 'chunk');
        const update = await request(start.url, chunk);
        if (!(update.offset > offset && update.offset <= file.size)) throw new Error('invalid_chunk');
        offset = update.offset;
        showProgress(100 * offset / file.size);
    }
    showProgress(null);
    const started = Date.now();
    for (;;) {
        const result = await request(start.url);
        if (result.state === 'ready') return {id: start.id, files: result.files};
        if (result.state !== 'checking') throw new Error(result.state);
        if (Date.now() - started >= 30 * 60 * 1000) throw new Error('unavailable');
        await wait(Math.min(3000, 500 + (Date.now() - started) / 10));
    }
}
