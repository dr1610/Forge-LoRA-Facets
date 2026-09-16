/* Extra Networks facet filters. Native search/sort/filter behavior stays in charge
 * of .hidden; our own data attribute adds an independent intersection. */
(() => {
    'use strict';
    let data = {items: [], genres: {}, job: {}}, byName = new Map();
    let loaded = false, loading = false, timer = null, pollTimer = null;
    const panels = new Map();
    const norm = value => value.toLowerCase().replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
    const baseKey = item => (typeof item.base_model === 'string' ? item.base_model.trim() : '') || '不明';
    function matches(item, state) {
        if (state.bases?.size && !state.bases.has(baseKey(item))) return false;
        if (state.genres.size && !item.genres.some(g => state.genres.has(g))) return false;
        const tags = new Set(item.tags.map(norm));
        const selected = [...state.tags];
        return !selected.length || (state.mode === 'or' ? selected.some(t => tags.has(t)) : selected.every(t => tags.has(t)));
    }
    // Public pure helper for integration tests; never overrides Forge globals.
    window.loraFacetsMatches = matches;
    const root = () => typeof gradioApp === 'function' ? gradioApp() : document;
    function el(tag, text, className) {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (className) node.className = className;
        return node;
    }
    function button(text, action, className) {
        const node = el('button', text, className);
        node.type = 'button';
        node.addEventListener('click', event => {
            event.preventDefault(); event.stopPropagation();
            Promise.resolve().then(action).catch(showError);
        });
        return node;
    }
    function showError(error) {
        for (const panel of panels.values()) {
            panel.status.textContent = 'エラー: ' + error.message;
            panel.status.dataset.error = 'true';
        }
    }
    async function api(path, body) {
        const base = new URL('./', window.location.href);
        const response = await fetch(new URL('lora-facets/' + path, base), {
            method: body === undefined ? 'GET' : 'POST',
            headers: {'X-LoRA-Facets': '1', 'Content-Type': 'application/json'},
            body: body === undefined ? undefined : JSON.stringify(body)
        });
        const value = await response.json();
        if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'HTTP ' + response.status);
        return value;
    }
    function accept(value) {
        data = value; byName = new Map(data.items.map(item => [item.name, item])); loaded = true;
        for (const panel of panels.values()) renderOptions(panel);
        applyAll();
        if (data.job.running && !pollTimer) {
            pollTimer = setTimeout(async () => {
                pollTimer = null;
                try { accept(await api('catalog')); } catch (err) { showError(err); }
            }, 1500);
        }
    }
    async function reload(rescan = false) {
        if (loading) return;
        loading = true;
        for (const panel of panels.values()) panel.status.textContent = '分類情報を読み込み中…';
        try { accept(await api(rescan ? 'rescan' : 'catalog', rescan ? {} : undefined)); }
        catch (err) { showError(err); }
        finally { loading = false; }
    }
    function persist(panel) {
        try { sessionStorage.setItem('lora-facets:' + panel.id, JSON.stringify({genres: [...panel.state.genres], tags: [...panel.state.tags], bases: [...panel.state.bases], mode: panel.state.mode})); }
        catch (_) { /* storage can be disabled */ }
    }
    function change(panel) {
        persist(panel); renderOptions(panel); applyAll();
    }
    function renderOptions(panel) {
        renderBases(panel);
        panel.genres.replaceChildren();
        const all = button('すべて', () => {panel.state.genres.clear(); change(panel);});
        all.setAttribute('aria-pressed', String(!panel.state.genres.size));
        panel.genres.append(all);
        for (const [key, label] of Object.entries(data.genres)) {
            const count = data.items.filter(item => item.genres.includes(key)).length;
            const b = button(label + ' ' + count, () => {
                if (panel.state.genres.has(key)) panel.state.genres.delete(key); else panel.state.genres.add(key);
                change(panel);
            });
            b.setAttribute('aria-pressed', String(panel.state.genres.has(key)));
            panel.genres.append(b);
        }
        panel.chips.replaceChildren();
        for (const base of panel.state.bases) {
            const chip = button(base + ' ×', () => {panel.state.bases.delete(base); change(panel);});
            chip.setAttribute('aria-label', 'ベースモデル ' + base + ' の絞り込みを解除'); panel.chips.append(chip);
        }
        for (const tag of panel.state.tags) {
            const chip = button(tag + ' ×', () => {panel.state.tags.delete(tag); change(panel);});
            chip.setAttribute('aria-label', tag + ' の絞り込みを解除'); panel.chips.append(chip);
        }
        renderTags(panel);
        panel.mode.value = panel.state.mode;
        panel.sync.disabled = !!data.job.running;
        panel.stop.disabled = !data.job.running;
        panel.status.dataset.error = data.error ? 'true' : 'false';
        const job = data.job;
        panel.status.textContent = data.error || (job.total || job.running ?
            `${job.message} (${job.done}/${job.total}・成功 ${job.ok}・失敗 ${job.errors})` :
            `${data.items.length}件の分類情報。未分類はカードの「分類編集」で修正できます。`);
    }
    function renderTags(panel) {
        const query = norm(panel.tagSearch.value);
        const counts = new Map();
        for (const item of data.items) {
            if (panel.state.bases.size && !panel.state.bases.has(baseKey(item))) continue;
            if (panel.state.genres.size && !item.genres.some(g => panel.state.genres.has(g))) continue;
            for (const tag of new Set(item.tags.map(norm))) counts.set(tag, (counts.get(tag) || 0) + 1);
        }
        const tags = [...counts.keys()].filter(t => !query || t.includes(query)).sort((a, b) => counts.get(b) - counts.get(a) || a.localeCompare(b));
        panel.tags.replaceChildren();
        for (const tag of tags.slice(0, 120)) {
            const b = button(`${tag} (${counts.get(tag)})`, () => {
                if (panel.state.tags.has(tag)) panel.state.tags.delete(tag); else panel.state.tags.add(tag);
                change(panel);
            });
            b.setAttribute('aria-pressed', String(panel.state.tags.has(tag))); panel.tags.append(b);
        }
        if (!tags.length) panel.tags.append(el('span', '該当するタグがありません'));
        if (tags.length > 120) panel.tags.append(el('span', `上位120件を表示（全${tags.length}件）。タグ名入力で絞り込めます。`));
    }
    function renderBases(panel) {
        panel.baseToggle.textContent = panel.state.bases.size ? `ベースモデル · ${panel.state.bases.size} 選択` : 'ベースモデル ▾';
        panel.baseToggle.setAttribute('aria-expanded', String(!panel.baseBox.hidden));
        const counts = new Map();
        for (const item of data.items) {const key = baseKey(item); counts.set(key, (counts.get(key) || 0) + 1);}
        for (const key of panel.state.bases) if (!counts.has(key)) counts.set(key, 0);
        const query = norm(panel.baseSearch.value);
        const focused = document.activeElement?.dataset.lfBase;
        panel.baseOptions.replaceChildren();
        for (const key of [...counts.keys()].sort((a,b) => a === '不明' ? 1 : b === '不明' ? -1 : a.localeCompare(b))) {
            if (query && !norm(key).includes(query)) continue;
            const b = button(`${key} (${counts.get(key)})`, () => {
                if (panel.state.bases.has(key)) panel.state.bases.delete(key); else panel.state.bases.add(key);
                change(panel);
            });
            b.dataset.lfBase = key;
            b.setAttribute('aria-pressed', String(panel.state.bases.has(key)));
            panel.baseOptions.append(b);
            if (focused === key) b.focus();
        }
        if (!panel.baseOptions.childElementCount) panel.baseOptions.append(el('span', '該当するベースモデルがありません'));
    }
    function mount(id) {
        const pane = root().getElementById(id + '_pane');
        if (!pane) return;
        let panel = panels.get(id);
        if (panel && panel.node.isConnected && panel.pane === pane) return;
        if (panel) {panel.observer.disconnect(); panel.node.remove();}
        let saved = {};
        try { saved = JSON.parse(sessionStorage.getItem('lora-facets:' + id) || '{}'); } catch (_) { /* defaults */ }
        const state = panel ? panel.state : {genres: new Set(saved.genres || []), tags: new Set(saved.tags || []), bases: new Set(saved.bases || []), mode: saved.mode === 'or' ? 'or' : 'and'};
        const node = el('section', undefined, 'lf-panel');
        node.setAttribute('aria-label', 'LoRA ジャンルとタグの絞り込み');
        panel = {id, node, state, pane}; panels.set(id, panel);
        const top = el('div', undefined, 'lf-row');
        top.append(el('strong', 'LoRA ジャンル'));
        panel.count = el('span', '', 'lf-count'); top.append(panel.count);
        panel.baseBox = el('div', undefined, 'lf-base-box'); panel.baseBox.hidden = true;
        panel.baseBox.id = id + '_lf_bases';
        panel.baseToggle = button('ベースモデル ▾', () => {
            panel.baseBox.hidden = !panel.baseBox.hidden;
            panel.baseToggle.setAttribute('aria-expanded', String(!panel.baseBox.hidden));
            if (!panel.baseBox.hidden) panel.baseSearch.focus();
        });
        panel.baseToggle.setAttribute('aria-controls', panel.baseBox.id);
        panel.baseToggle.setAttribute('aria-expanded', 'false');
        top.append(panel.baseToggle);
        const baseHeader = el('div', undefined, 'lf-row');
        baseHeader.append(el('strong', 'ベースモデル（複数選択・OR）'));
        panel.baseSearch = el('input'); panel.baseSearch.type = 'search'; panel.baseSearch.placeholder = 'ベースモデルを探す';
        panel.baseSearch.setAttribute('aria-label', 'ベースモデル候補を検索');
        panel.baseSearch.addEventListener('input', () => renderBases(panel));
        baseHeader.append(panel.baseSearch, button('モデル選択を解除', () => {state.bases.clear(); panel.baseSearch.value = ''; change(panel);}));
        baseHeader.append(button('閉じる', () => {panel.baseBox.hidden = true; panel.baseToggle.setAttribute('aria-expanded','false'); panel.baseToggle.focus();}));
        panel.baseOptions = el('div', undefined, 'lf-base-options');
        panel.baseBox.append(baseHeader, panel.baseOptions, el('p', 'Civitaiのベースモデル名で絞り込みます。Forge標準フィルターで非表示のLoRAは表示されません。'));
        panel.baseBox.addEventListener('keydown', event => {
            if (event.key === 'Escape') {event.stopPropagation(); panel.baseBox.hidden = true; panel.baseToggle.setAttribute('aria-expanded','false'); panel.baseToggle.focus();}
        });
        top.append(button('絞り込み解除', () => {state.genres.clear(); state.tags.clear(); state.bases.clear(); panel.tagSearch.value = ''; panel.baseSearch.value = ''; change(panel);}));
        top.append(button('分類情報を再読込', () => reload(true)));
        panel.sync = button('不足情報をCivitaiから取得', async () => {
            await api('sync', {}); await reload();
        });
        panel.sync.title = 'タグ情報がないLoRAを取得します。照合にモデルIDまたはファイルのSHA256ハッシュを送信します。モデル本体は送信しません。';
        panel.stop = button('取得停止', async () => {await api('stop', {}); await reload();});
        top.append(panel.sync, panel.stop);
        panel.genres = el('div', undefined, 'lf-genres');
        panel.chips = el('div', undefined, 'lf-chips');
        const details = el('details', undefined, 'lf-tag-details');
        details.append(el('summary', 'タグで絞り込む（ジャンル間はOR・ジャンルとタグと既存検索はAND）'));
        const controls = el('div', undefined, 'lf-row');
        panel.tagSearch = el('input'); panel.tagSearch.type = 'search'; panel.tagSearch.placeholder = 'タグを探す';
        panel.tagSearch.setAttribute('aria-label', 'タグ候補を検索');
        panel.tagSearch.addEventListener('input', () => renderTags(panel));
        panel.mode = el('select'); panel.mode.setAttribute('aria-label', 'タグの一致条件');
        for (const [key, text] of [['and', 'すべて含む（AND）'], ['or', 'どれか含む（OR）']]) {
            const option = el('option', text); option.value = key; panel.mode.append(option);
        }
        panel.mode.addEventListener('change', () => {state.mode = panel.mode.value; change(panel);});
        controls.append(panel.tagSearch, panel.mode);
        panel.tags = el('div', undefined, 'lf-tags'); details.append(controls, panel.tags);
        panel.status = el('div', '分類情報を読み込み中…', 'lf-status'); panel.status.setAttribute('role', 'status');
        node.append(top, panel.baseBox, panel.genres, panel.chips, details, panel.status);
        pane.before(node);
        if (loaded) renderOptions(panel);
        const observer = new MutationObserver(schedule);
        observer.observe(pane, {childList: true, subtree: true, attributes: true, attributeFilter: ['class']});
        if (panel.observer) panel.observer.disconnect();
        panel.observer = observer;
    }
    function applyAll() {
        for (const panel of panels.values()) {
            let shown = 0, total = 0;
            root().querySelectorAll('#' + panel.id + '_cards .card').forEach(card => {
                total++;
                const name = card.getAttribute('data-name');
                const item = byName.get(name) || {genres: ['unclassified'], tags: []};
                const hidden = !matches(item, panel.state);
                if (hidden) card.setAttribute('data-lf-hidden', '1'); else card.removeAttribute('data-lf-hidden');
                if (!hidden && !card.classList.contains('hidden')) shown++;
                if (!card.querySelector('.lf-edit')) {
                    const edit = button('分類編集', () => openEditor(name), 'lf-edit');
                    card.append(edit);
                }
            });
            const label = `${shown} / ${total} 件表示`;
            if (panel.count.textContent !== label) panel.count.textContent = label;
        }
    }
    function openEditor(name) {
        const item = byName.get(name);
        if (!item) throw new Error('分類情報を再読込してから編集してください');
        const old = document.querySelector('.lf-dialog'); if (old) old.remove();
        const dialog = el('dialog', undefined, 'lf-dialog');
        dialog.setAttribute('aria-label', 'LoRAの分類編集');
        dialog.append(el('h3', '分類編集: ' + name));
        dialog.append(el('p', `${item.source}${item.manual ? '／手動修正あり' : ''}${item.base_model ? '／' + item.base_model : ''}`));
        if (item.status && item.status !== '取得済み') dialog.append(el('p', item.status));
        for (const warning of item.warnings || []) dialog.append(el('p', warning));
        const fields = el('fieldset'); fields.append(el('legend', 'ジャンル（複数選択可）'));
        const checkboxes = [];
        for (const [key, label] of Object.entries(data.genres)) {
            const wrap = el('label'); const input = el('input'); input.type = 'checkbox'; input.value = key;
            input.checked = item.genres.includes(key); checkboxes.push(input); wrap.append(input, document.createTextNode(label)); fields.append(wrap);
        }
        const tagLabel = el('label', 'タグ（カンマまたは改行で区切る）');
        const tagInput = el('textarea'); tagInput.value = item.tags.join(', '); tagInput.rows = 5;
        tagLabel.append(tagInput); dialog.append(fields, tagLabel);
        const status = el('p', '手動修正はCivitai情報を再取得しても保持されます。'); status.setAttribute('role', 'status');
        const actions = el('div', undefined, 'lf-row');
        const run = action => async () => {
            try { await action(); } catch (err) {status.textContent = 'エラー: ' + err.message;}
        };
        actions.append(button('保存', run(async () => {
            await api('edit', {id: item.id, genres: checkboxes.filter(c => c.checked).map(c => c.value), tags: tagInput.value.split(/[,，、\n]/).map(t => t.trim()).filter(Boolean)});
            await reload(); dialog.close();
        })));
        actions.append(button('自動分類に戻す', run(async () => {await api('edit', {id: item.id, reset: true}); await reload(); dialog.close();})));
        actions.append(button('このLoRAのCivitai情報を取得', run(async () => {await api('sync', {ids: [item.id]}); await reload(); dialog.close();})));
        actions.append(button('閉じる', () => dialog.close()));
        dialog.append(status, actions); dialog.addEventListener('close', () => dialog.remove());
        document.body.append(dialog); dialog.showModal();
    }
    function setup() {
        for (const id of ['txt2img_lora', 'img2img_lora']) mount(id);
        if (panels.size && !loaded && !loading) reload();
        applyAll();
    }
    function schedule() {clearTimeout(timer); timer = setTimeout(setup, 100);}
    if (typeof onUiLoaded === 'function') onUiLoaded(setup);
    if (typeof onUiUpdate === 'function') onUiUpdate(schedule);
})();
