/* Local Knowledge — client-side app */

const API = '/api';

// -- API helpers --------------------------------------------------------------

async function apiGet(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function apiDelete(path) {
  const res = await fetch(`${API}${path}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// -- State --------------------------------------------------------------------

let currentView = 'browse'; // 'browse' | 'search' | 'chunks'
let projects = [];

// -- Init ---------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  loadStats();
  loadDocuments();
  loadProjects();

  document.getElementById('search-form').addEventListener('submit', (e) => {
    e.preventDefault();
    doSearch();
  });

  document.getElementById('browse-btn').addEventListener('click', () => {
    closeDetail();
    loadDocuments();
  });

  document.getElementById('add-form').addEventListener('submit', (e) => {
    e.preventDefault();
    addDocument();
  });

  document.getElementById('close-detail').addEventListener('click', closeDetail);
});

// -- Stats --------------------------------------------------------------------

async function loadStats() {
  try {
    const stats = await apiGet('/stats');
    const bar = document.getElementById('stats-bar');
    bar.textContent = `${stats.total} docs | ${stats.embedded} embedded | ${stats.unembedded} pending`;
  } catch (e) {
    console.error('Failed to load stats:', e);
  }
}

// -- Documents ----------------------------------------------------------------

async function loadDocuments() {
  currentView = 'browse';
  const list = document.getElementById('results-list');
  list.innerHTML = '<div class="empty">Loading...</div>';
  try {
    const docs = await apiGet('/documents?limit=50');
    renderDocumentList(docs);
  } catch (e) {
    list.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
}

function renderDocumentList(docs) {
  const list = document.getElementById('results-list');
  if (!docs.length) {
    list.innerHTML = '<div class="empty">No documents yet. Add one below.</div>';
    return;
  }
  list.innerHTML = docs.map(doc => `
    <div class="result-item" data-id="${doc.id}" onclick="showDocument('${doc.id}')">
      <div class="result-title">${esc(doc.title)}</div>
      <div class="result-meta">
        <span>${doc.source_type}</span>
        <span>${doc.ingest_status}</span>
        <span>${doc.created_at.slice(0, 19)}</span>
        <span>${doc.id.slice(0, 12)}</span>
      </div>
    </div>
  `).join('');
}

// -- Projects -----------------------------------------------------------------

async function loadProjects() {
  try {
    projects = await apiGet('/projects');
    const sel = document.getElementById('project-filter');
    if (!sel) return;
    sel.innerHTML = '<option value="">All projects</option>' +
      projects.map(p => `<option value="${esc(p.slug)}">${esc(p.name)} (${p.doc_count})</option>`).join('');
  } catch (e) {
    console.error('Failed to load projects:', e);
  }
}

// -- Search -------------------------------------------------------------------

async function doSearch() {
  const query = document.getElementById('search-input').value.trim();
  if (!query) return loadDocuments();

  const mode = document.getElementById('search-mode').value;
  const chunks = document.getElementById('chunks-toggle').checked;
  const projectSel = document.getElementById('project-filter');
  const projectSlug = projectSel ? projectSel.value : '';
  const list = document.getElementById('results-list');
  list.innerHTML = '<div class="empty">Searching...</div>';
  closeDetail();

  try {
    if (chunks) {
      currentView = 'chunks';
      const results = await apiGet(`/search/chunks?q=${encodeURIComponent(query)}&limit=20`);
      // Client-side project filter for chunks
      if (projectSlug) {
        const projDocs = await apiGet(`/projects/${projectSlug}/documents?limit=10000`);
        const projIds = new Set(projDocs.map(d => d.id));
        renderChunkResults(results.filter(r => projIds.has(r.document_id)));
      } else {
        renderChunkResults(results);
      }
    } else {
      currentView = 'search';
      const results = await apiGet(`/search?q=${encodeURIComponent(query)}&mode=${mode}&limit=20`);
      if (projectSlug) {
        const projDocs = await apiGet(`/projects/${projectSlug}/documents?limit=10000`);
        const projIds = new Set(projDocs.map(d => d.id));
        renderSearchResults(results.filter(r => projIds.has(r.id)));
      } else {
        renderSearchResults(results);
      }
    }
  } catch (e) {
    list.innerHTML = `<div class="empty">Search failed: ${e.message}</div>`;
  }
}

function renderSearchResults(results) {
  const list = document.getElementById('results-list');
  if (!results.length) {
    list.innerHTML = '<div class="empty">No results found.</div>';
    return;
  }
  list.innerHTML = results.map(r => `
    <div class="result-item" data-id="${r.id}" onclick="showDocument('${r.id}')">
      <div class="result-title">${esc(r.title)}</div>
      <div class="result-meta">
        <span class="result-score">${r.score.toFixed(4)}</span>
        <span>${r.source}</span>
        <span>${r.source_type}</span>
        <span>${r.id.slice(0, 12)}</span>
      </div>
    </div>
  `).join('');
}

function renderChunkResults(results) {
  const list = document.getElementById('results-list');
  if (!results.length) {
    list.innerHTML = '<div class="empty">No chunk results found.</div>';
    return;
  }
  list.innerHTML = results.map(r => `
    <div class="chunk-item">
      <div class="result-meta">
        <span class="result-score">${r.score.toFixed(4)}</span>
        <span>Doc: ${r.document_id.slice(0, 12)}</span>
        <span>Chunk #${r.chunk_index}</span>
      </div>
      <div class="chunk-excerpt">${esc(r.chunk_text.slice(0, 300))}${r.chunk_text.length > 300 ? '...' : ''}</div>
    </div>
  `).join('');
}

// -- Detail -------------------------------------------------------------------

async function showDocument(docId) {
  const panel = document.getElementById('detail-panel');
  const content = document.getElementById('detail-content');
  const area = document.getElementById('content-area');

  // Highlight active item
  document.querySelectorAll('.result-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === docId);
  });

  panel.classList.remove('hidden');
  area.classList.add('with-detail');
  content.innerHTML = '<div class="empty">Loading...</div>';

  try {
    const doc = await apiGet(`/documents/${docId}`);
    renderDetail(doc);
  } catch (e) {
    content.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
}

function renderDetail(doc) {
  const content = document.getElementById('detail-content');
  const tags = (doc.tags || []).map(t =>
    `<span class="tag-badge">${esc(t.name)}</span>`
  ).join('');

  const preview = doc.content
    ? `<div class="detail-content">${esc(doc.content)}</div>`
    : '<div class="detail-field"><em>No content</em></div>';

  content.innerHTML = `
    <div class="detail-title">${esc(doc.title)}</div>
    <div class="detail-field"><strong>ID:</strong> ${doc.id}</div>
    <div class="detail-field"><strong>Type:</strong> ${doc.source_type}</div>
    <div class="detail-field"><strong>Status:</strong> ${doc.ingest_status}</div>
    <div class="detail-field"><strong>Created:</strong> ${doc.created_at}</div>
    ${doc.source_uri ? `<div class="detail-field"><strong>Source:</strong> ${esc(doc.source_uri)}</div>` : ''}
    ${doc.chunk_count != null ? `<div class="detail-field"><strong>Chunks:</strong> ${doc.chunk_count}</div>` : ''}
    <div class="detail-tags">${tags || '<span style="color:#999">No tags</span>'}</div>
    <div class="tag-form">
      <input type="text" id="tag-input" placeholder="Add tag...">
      <button type="button" onclick="addTag('${doc.id}')">Tag</button>
    </div>
    ${preview}
    <div class="detail-actions">
      <button class="danger" onclick="deleteDoc('${doc.id}')">Delete</button>
    </div>
  `;
}

function closeDetail() {
  document.getElementById('detail-panel').classList.add('hidden');
  document.getElementById('content-area').classList.remove('with-detail');
  document.querySelectorAll('.result-item.active').forEach(el => el.classList.remove('active'));
}

// -- Actions ------------------------------------------------------------------

async function addDocument() {
  const text = document.getElementById('add-text').value.trim();
  if (!text) return;
  const title = document.getElementById('add-title').value.trim() || null;
  const sourceType = document.getElementById('add-type').value;

  try {
    await apiPost('/documents', { text, title, source_type: sourceType });
    document.getElementById('add-text').value = '';
    document.getElementById('add-title').value = '';
    loadStats();
    loadDocuments();
  } catch (e) {
    alert('Failed to add document: ' + e.message);
  }
}

async function addTag(docId) {
  const input = document.getElementById('tag-input');
  const name = input.value.trim();
  if (!name) return;
  try {
    await apiPost(`/documents/${docId}/tags`, { name });
    input.value = '';
    showDocument(docId);
  } catch (e) {
    alert('Failed to tag: ' + e.message);
  }
}

async function deleteDoc(docId) {
  if (!confirm('Delete this document?')) return;
  try {
    await apiDelete(`/documents/${docId}`);
    closeDetail();
    loadStats();
    loadDocuments();
  } catch (e) {
    alert('Failed to delete: ' + e.message);
  }
}

// -- Util ---------------------------------------------------------------------

function esc(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
