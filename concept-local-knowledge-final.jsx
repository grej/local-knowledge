import { useState, useRef, useEffect, useMemo } from "react";

const font = {
  sans: "'DM Sans', 'Avenir Next', system-ui, sans-serif",
  mono: "'JetBrains Mono', 'SF Mono', monospace",
  serif: "'Source Serif 4', Georgia, serif",
};

const c = {
  bg: "#0c0d12",
  bgDeep: "#08090d",
  surface: "#13151d",
  surfaceRaised: "#1a1d27",
  surfaceHover: "#1e2130",
  border: "#222538",
  borderLight: "#2c3048",
  text: "#e4e5ea",
  textSecondary: "#a0a4b8",
  textMuted: "#6b7084",
  textDim: "#464b5e",
  accent: "#6c8cff",
  accentDim: "rgba(108,140,255,0.10)",
  accentMed: "rgba(108,140,255,0.20)",
  green: "#4ade80",
  greenDim: "rgba(74,222,128,0.10)",
  amber: "#f59e0b",
  amberDim: "rgba(245,158,11,0.10)",
  purple: "#a78bfa",
  purpleDim: "rgba(167,139,250,0.10)",
  red: "#f87171",
  redDim: "rgba(248,113,113,0.10)",
  cyan: "#22d3ee",
  cyanDim: "rgba(34,211,238,0.10)",
};

// ─── Mock data ──────────────────────────────────────────────
const docs = [
  { id: "a93764a7", title: "The A-10 is reborn in the Iran war", type: "article", status: "error", date: "2026-03-23T04:25:06", source: "asiatimes.com", chunks: 9, tags: ["defense", "iran-war", "project:crm"], snippet: "Despite years of effort by the Air Force to get rid of the A-10 fleet, the A-10 is playing a major role in the Iran war. Unlike its predecessors used in the Iraq wars, the A-10 has been reborn with new equipment, better weapons, and significantly enhanced networking capabilities, plus embedded artificial intelligence to enhance accuracy and lethality of the platform." },
  { id: "51daf84f", title: "Seagull 3D Asset - Prompt to Finish : r/aigamedev", type: "article", status: "indexed", date: "2026-03-23T04:21:10", source: "reddit.com", chunks: 4, tags: ["gamedev", "3d-assets", "ai-tools", "project:silent-service"], snippet: "A comprehensive walkthrough of generating game-ready 3D assets using AI-assisted workflows, from initial prompt design through UV unwrapping and texture baking. The pipeline uses a combination of Meshy, Blender, and Substance Painter for production-quality results." },
  { id: "5f79987c", title: 'What is the best NSFW "Image Editing" model for Comfy UI? : comfyui', type: "article", status: "indexed", date: "2026-03-23T04:19:11", source: "reddit.com", chunks: 6, tags: ["comfyui", "image-gen", "ai-tools"], snippet: "Community discussion comparing various image editing models compatible with ComfyUI, covering inpainting quality, speed, and VRAM requirements across different hardware configurations including RTX 4090 and Apple Silicon." },
  { id: "ec39de0d", title: "March 21, 2026 - by Heather Cox Richardson", type: "article", status: "indexed", date: "2026-03-23T03:33:43", source: "substack.com", chunks: 11, tags: ["politics", "hcr", "iran-war", "project:crm"], snippet: "The recognition that the war might drag on has driven the stock market down sharply. All three of the main U.S. stock indexes—the S&P 500, the Nasdaq Composite, and the Dow Jones Industrial Average—have fallen since the war began. Tonight, after markets had closed down again, Trump appeared to try to reassure the country." },
  { id: "cec46d98", title: "(1) March 20, 2026 - by Heather Cox Richardson", type: "article", status: "indexed", date: "2026-03-21T18:04:56", source: "substack.com", chunks: 12, tags: ["politics", "hcr", "iran-war", "project:crm"], snippet: "On Wednesday, Israeli forces hit Iranian facilities in the South Pars natural gas field in the Persian Gulf, shared by Iran and Qatar. Helen Regan and Ivana Kottasová of CNN explain that the South Pars gas field is part of the largest natural gas reserve in the world." },
  { id: "1d626a2f", title: "Solar panels and renewable energy policy in Germany", type: "note", status: "raw", date: "2026-03-21T14:39:48", source: "manual entry", chunks: 2, tags: ["energy", "europe", "policy"], snippet: "Notes on Germany's Energiewende policy trajectory and implications for EU energy independence. Solar capacity additions accelerating despite grid integration challenges. Key consideration for Ireland relocation research and European energy security analysis." },
  { id: "b7e42f1a", title: "Knowledge Distillation for Compact NLP Models", type: "article", status: "indexed", date: "2026-03-20T22:15:33", source: "arxiv.org", chunks: 8, tags: ["ml", "distillation", "nlp", "project:spock"], snippet: "Survey of knowledge distillation techniques applicable to creating specialist models from larger teacher networks. Covers response-based, feature-based, and relation-based approaches with benchmarks on GLUE tasks. Particularly relevant for fine-tuning compact grading models." },
  { id: "c3f891d2", title: "FSRS Algorithm Deep Dive - Optimizing Spaced Repetition", type: "article", status: "indexed", date: "2026-03-19T16:40:12", source: "github.com", chunks: 7, tags: ["fsrs", "spaced-repetition", "algorithms", "project:spock"], snippet: "Detailed explanation of the Free Spaced Repetition Scheduler algorithm, covering the mathematical foundations, parameter optimization via maximum likelihood estimation, and comparison with SM-2 and Anki's default scheduler." },
  { id: "d5a103e8", title: "F1-Kadane Equivalence and Optimal Interval Discovery", type: "note", status: "indexed", date: "2026-03-18T11:22:05", source: "manual entry", chunks: 3, tags: ["algorithms", "f1-score", "optimization", "project:mountain-discovery"], snippet: "Working notes on the proof that maximizing weighted F1 score over contiguous intervals is equivalent to the maximum subarray problem via Kadane's algorithm, enabling O(n log n) exact solutions for optimal threshold discovery." },
  { id: "e8f210ab", title: "Convoy Formation Patterns in WWII North Atlantic", type: "article", status: "indexed", date: "2026-03-16T09:15:22", source: "naval-history.net", chunks: 5, tags: ["naval", "wwii", "convoy", "project:silent-service"], snippet: "Analysis of Allied convoy formation tactics, escort screen geometry, and the evolution of anti-submarine warfare doctrine from 1940 to 1943. Covers the shift from close escort to hunter-killer group tactics after the mid-Atlantic air gap was closed." },
];

// ─── Simulated hybrid search ────────────────────────────────
// In production this calls the local-knowledge API which does
// FTS5 + dense embedding search with RRF fusion
function hybridSearch(query, documents) {
  if (!query.trim()) return documents.map((d) => ({ ...d, score: null }));
  const q = query.toLowerCase();

  // Simulate: keyword component (FTS5)
  const keywordScores = documents.map((d) => {
    let score = 0;
    const fields = [d.title, d.snippet, ...d.tags, d.source];
    fields.forEach((f) => {
      const fl = f.toLowerCase();
      if (fl.includes(q)) score += 0.3;
      q.split(/\s+/).forEach((w) => { if (w.length > 2 && fl.includes(w)) score += 0.15; });
    });
    return score;
  });

  // Simulate: semantic component (embedding similarity)
  // Conceptual neighbors get boosted even without keyword match
  const semanticMap = {
    "war": ["defense", "iran-war", "naval", "convoy", "politics"],
    "iran": ["iran-war", "defense", "politics", "hcr"],
    "machine learning": ["ml", "distillation", "nlp", "algorithms", "f1-score"],
    "ai": ["ml", "ai-tools", "distillation", "nlp", "image-gen"],
    "algorithm": ["algorithms", "f1-score", "optimization", "fsrs", "spaced-repetition"],
    "study": ["fsrs", "spaced-repetition", "distillation"],
    "submarine": ["naval", "convoy", "wwii", "project:silent-service"],
    "game": ["gamedev", "3d-assets", "project:silent-service"],
    "energy": ["energy", "europe", "policy"],
    "politics": ["politics", "hcr", "iran-war", "project:crm"],
    "optimization": ["optimization", "f1-score", "algorithms"],
    "model": ["ml", "distillation", "nlp", "image-gen", "comfyui"],
    "spaced repetition": ["fsrs", "spaced-repetition", "project:spock"],
    "threshold": ["f1-score", "optimization", "algorithms"],
  };

  const semanticScores = documents.map((d) => {
    let score = 0;
    Object.entries(semanticMap).forEach(([concept, relatedTags]) => {
      if (q.includes(concept) || concept.includes(q)) {
        const overlap = d.tags.filter((t) => relatedTags.includes(t)).length;
        score += overlap * 0.12;
      }
    });
    return score;
  });

  // RRF-style fusion
  const combined = documents.map((d, i) => ({
    ...d,
    score: Math.min(0.99, keywordScores[i] + semanticScores[i]),
  }));

  return combined
    .filter((d) => d.score > 0.05)
    .sort((a, b) => b.score - a.score);
}

function findSimilar(doc, allDocs) {
  // Simulate embedding-based similarity by tag overlap + boost for same project
  return allDocs
    .filter((d) => d.id !== doc.id)
    .map((d) => {
      const tagOverlap = d.tags.filter((t) => doc.tags.includes(t)).length;
      const projectMatch = d.tags.some((t) => t.startsWith("project:") && doc.tags.includes(t)) ? 0.15 : 0;
      const score = Math.min(0.99, (tagOverlap * 0.18) + projectMatch + Math.random() * 0.05);
      return { ...d, score };
    })
    .filter((d) => d.score > 0.1)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);
}

// ─── Tag index ──────────────────────────────────────────────
function buildTagIndex(documents) {
  const index = {};
  documents.forEach((d) => {
    d.tags.forEach((t) => {
      if (!index[t]) index[t] = { tag: t, count: 0, isProject: t.startsWith("project:") };
      index[t].count++;
    });
  });
  return Object.values(index).sort((a, b) => {
    if (a.isProject !== b.isProject) return a.isProject ? -1 : 1;
    return b.count - a.count;
  });
}

// ─── Time helpers ───────────────────────────────────────────
function timeAgo(dateStr) {
  const d = new Date(dateStr);
  const now = new Date("2026-03-23T12:00:00");
  const hours = Math.floor((now - d) / 3600000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return `${days}d ago`;
}

function withinRange(dateStr, range) {
  if (range === "all") return true;
  const d = new Date(dateStr);
  const now = new Date("2026-03-23T12:00:00");
  const days = (now - d) / 86400000;
  if (range === "7d") return days <= 7;
  if (range === "30d") return days <= 30;
  return true;
}

// ─── Components ─────────────────────────────────────────────
function FilterChip({ tag, onRemove }) {
  const isProject = tag.startsWith("project:");
  const display = isProject ? tag.replace("project:", "") : tag;
  const chipColor = isProject ? c.purple : c.accent;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "3px 5px 3px 9px", borderRadius: 6,
      background: isProject ? c.purpleDim : c.accentDim,
      color: chipColor, border: `1px solid ${chipColor}33`,
      fontSize: 11, fontWeight: 500,
    }}>
      {isProject && <span style={{ fontSize: 9, opacity: 0.6 }}>⬡</span>}
      {display}
      <span onClick={(e) => { e.stopPropagation(); onRemove(); }}
        style={{ width: 16, height: 16, borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 10, color: chipColor }}
        onMouseEnter={(e) => e.target.style.background = `${chipColor}22`}
        onMouseLeave={(e) => e.target.style.background = "transparent"}
      >×</span>
    </span>
  );
}

function StatusDot({ status }) {
  const color = status === "indexed" ? c.green : status === "error" ? c.red : c.amber;
  return <span style={{ width: 6, height: 6, borderRadius: "50%", background: color, display: "inline-block", flexShrink: 0 }} />;
}

function StatusBadge({ status }) {
  const color = status === "indexed" ? c.green : status === "error" ? c.red : c.amber;
  const bg = status === "indexed" ? c.greenDim : status === "error" ? c.redDim : c.amberDim;
  return <span style={{ fontSize: 10, fontWeight: 500, padding: "2px 7px", borderRadius: 4, color, background: bg, border: `1px solid ${color}22` }}>{status}</span>;
}

function ScoreBadge({ score }) {
  if (score === null || score === undefined) return null;
  const pct = Math.round(score * 100);
  const color = pct > 60 ? c.green : pct > 30 ? c.amber : c.textDim;
  return (
    <span style={{
      fontSize: 10, fontFamily: font.mono, fontWeight: 600,
      color, padding: "2px 6px", borderRadius: 4,
      background: `${color}15`, border: `1px solid ${color}22`,
      minWidth: 36, textAlign: "center", display: "inline-block",
    }}>.{String(pct).padStart(2, "0")}</span>
  );
}

// ─── Tag Dropdown ───────────────────────────────────────────
function TagDropdown({ allTags, activeFilters, onAdd, onClose }) {
  const [query, setQuery] = useState("");
  const ref = useRef(null);
  useEffect(() => { ref.current?.focus(); }, []);

  const available = allTags.filter((t) =>
    !activeFilters.includes(t.tag) &&
    (query === "" || t.tag.toLowerCase().includes(query.toLowerCase()))
  );
  const projectTags = available.filter((t) => t.isProject);
  const topicTags = available.filter((t) => !t.isProject);

  return (
    <div style={{
      position: "absolute", top: "100%", left: 0, width: 240,
      background: c.surfaceRaised, border: `1px solid ${c.borderLight}`,
      borderRadius: 10, marginTop: 4, zIndex: 50,
      boxShadow: "0 12px 40px rgba(0,0,0,0.5)",
      maxHeight: 300, overflow: "hidden", display: "flex", flexDirection: "column",
    }}>
      <div style={{ padding: "8px 10px", borderBottom: `1px solid ${c.border}` }}>
        <input ref={ref} type="text" value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            if (e.key === "Enter" && available.length > 0) { onAdd(available[0].tag); setQuery(""); }
          }}
          placeholder="Search tags..."
          style={{ width: "100%", padding: "6px 8px", borderRadius: 6, border: `1px solid ${c.border}`, background: c.bg, color: c.text, fontSize: 12, fontFamily: font.sans, outline: "none", boxSizing: "border-box" }}
        />
      </div>
      <div style={{ overflow: "auto", flex: 1 }}>
        {projectTags.length > 0 && <>
          <div style={{ padding: "8px 12px 4px", fontSize: 9, fontWeight: 700, color: c.textDim, textTransform: "uppercase", letterSpacing: "0.08em" }}>Projects</div>
          {projectTags.map((t) => <TagItem key={t.tag} tag={t} onAdd={onAdd} />)}
        </>}
        {topicTags.length > 0 && <>
          <div style={{ padding: "8px 12px 4px", fontSize: 9, fontWeight: 700, color: c.textDim, textTransform: "uppercase", letterSpacing: "0.08em" }}>Topics</div>
          {topicTags.map((t) => <TagItem key={t.tag} tag={t} onAdd={onAdd} />)}
        </>}
        {available.length === 0 && <div style={{ padding: 16, fontSize: 12, color: c.textDim, textAlign: "center" }}>{query ? "No matches" : "All tags active"}</div>}
      </div>
    </div>
  );
}

function TagItem({ tag, onAdd }) {
  const [h, setH] = useState(false);
  const display = tag.isProject ? tag.tag.replace("project:", "") : tag.tag;
  return (
    <div onClick={() => onAdd(tag.tag)} onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)}
      style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 12px", cursor: "pointer", background: h ? c.surfaceHover : "transparent", transition: "background 0.08s" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {tag.isProject && <span style={{ fontSize: 10, color: c.purple, opacity: 0.5 }}>⬡</span>}
        <span style={{ fontSize: 12, color: h ? c.text : c.textSecondary }}>{display}</span>
      </div>
      <span style={{ fontSize: 10, color: c.textDim, padding: "1px 6px", borderRadius: 3, background: c.bg }}>{tag.count}</span>
    </div>
  );
}

// ─── Main App ───────────────────────────────────────────────
export default function App() {
  const [activeFilters, setActiveFilters] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [tagDropdownOpen, setTagDropdownOpen] = useState(false);
  const [sortMode, setSortMode] = useState("auto"); // auto, date, relevance
  const [timeRange, setTimeRange] = useState("all");
  const [similarMode, setSimilarMode] = useState(null); // doc id when showing "find similar"
  const dropdownRef = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (dropdownRef.current && !dropdownRef.current.contains(e.target)) setTagDropdownOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const tagIndex = useMemo(() => buildTagIndex(docs), []);

  // Determine effective sort: auto means date when browsing, relevance when searching
  const isSearching = searchQuery.trim().length > 0;
  const effectiveSort = sortMode === "auto" ? (isSearching ? "relevance" : "date") : sortMode;

  // Build result set
  const results = useMemo(() => {
    // If "find similar" mode, use similarity search
    if (similarMode) {
      const sourceDoc = docs.find((d) => d.id === similarMode);
      if (sourceDoc) return findSimilar(sourceDoc, docs);
    }

    // Otherwise: filter by tags → filter by time → hybrid search or list all
    let pool = docs;
    if (activeFilters.length > 0) {
      pool = pool.filter((d) => activeFilters.every((f) => d.tags.includes(f)));
    }
    pool = pool.filter((d) => withinRange(d.date, timeRange));

    if (isSearching) {
      const searched = hybridSearch(searchQuery, pool);
      if (effectiveSort === "date") {
        return searched.sort((a, b) => new Date(b.date) - new Date(a.date));
      }
      return searched; // already sorted by relevance
    }

    // Browsing: sort by date
    const withNullScore = pool.map((d) => ({ ...d, score: null }));
    if (effectiveSort === "date") {
      return withNullScore.sort((a, b) => new Date(b.date) - new Date(a.date));
    }
    return withNullScore;
  }, [activeFilters, searchQuery, timeRange, effectiveSort, similarMode]);

  // Auto-select first result
  useEffect(() => {
    if (results.length > 0 && (!selectedDoc || !results.find((d) => d.id === selectedDoc.id))) {
      setSelectedDoc(results[0]);
    } else if (results.length === 0) {
      setSelectedDoc(null);
    }
  }, [results]);

  const addFilter = (tag) => { if (!activeFilters.includes(tag)) setActiveFilters([...activeFilters, tag]); };
  const removeFilter = (tag) => setActiveFilters(activeFilters.filter((f) => f !== tag));
  const clearAll = () => { setActiveFilters([]); setSearchQuery(""); setTimeRange("all"); setSimilarMode(null); setSortMode("auto"); };

  const handleFindSimilar = (doc) => {
    setSimilarMode(doc.id);
    setActiveFilters([]);
    setSearchQuery("");
    setTimeRange("all");
  };

  const exitSimilarMode = () => { setSimilarMode(null); };

  const hasActiveScope = activeFilters.length > 0 || isSearching || timeRange !== "all" || similarMode;

  return (
    <div style={{ height: "100vh", background: c.bgDeep, fontFamily: font.sans, display: "flex", flexDirection: "column" }}>
      <style>{`
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: ${c.border}; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: ${c.borderLight}; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>

      {/* ─── Top Bar ──────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 20px", borderBottom: `1px solid ${c.border}`, background: c.bg, flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: c.green }} />
          <span style={{ fontSize: 14, fontWeight: 700, color: c.text }}>Local Knowledge</span>
        </div>
        <span style={{ fontSize: 11, color: c.textDim }}>{docs.length} docs · {docs.filter((d) => d.status === "indexed").length} embedded</span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: c.textDim, fontFamily: font.mono }}>127.0.0.1:8321</span>
      </div>

      {/* ─── Filter Bar ──────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 20px", borderBottom: `1px solid ${c.border}`, background: c.surface, flexShrink: 0, flexWrap: "wrap", minHeight: 44 }}>

        {/* Similar mode banner */}
        {similarMode && (
          <div style={{
            display: "flex", alignItems: "center", gap: 6, padding: "3px 5px 3px 10px",
            borderRadius: 6, background: c.cyanDim, border: `1px solid ${c.cyan}33`,
            fontSize: 11, color: c.cyan, fontWeight: 500,
          }}>
            ◎ Similar to: {docs.find((d) => d.id === similarMode)?.title.slice(0, 35)}...
            <span onClick={exitSimilarMode} style={{ cursor: "pointer", padding: "0 4px", fontSize: 10 }}
              onMouseEnter={(e) => e.target.style.background = `${c.cyan}22`}
              onMouseLeave={(e) => e.target.style.background = "transparent"}
            >×</span>
          </div>
        )}

        {/* Tag filter chips */}
        {!similarMode && activeFilters.map((f) => <FilterChip key={f} tag={f} onRemove={() => removeFilter(f)} />)}

        {/* Add tag button */}
        {!similarMode && (
          <div ref={dropdownRef} style={{ position: "relative" }}>
            <button onClick={() => setTagDropdownOpen(!tagDropdownOpen)} style={{
              display: "flex", alignItems: "center", gap: 4, padding: "3px 9px", borderRadius: 6,
              border: `1px dashed ${tagDropdownOpen ? c.accent + "66" : c.border}`,
              background: tagDropdownOpen ? c.accentDim : "transparent",
              color: tagDropdownOpen ? c.accent : c.textMuted,
              fontSize: 11, fontFamily: font.sans, cursor: "pointer", transition: "all 0.12s",
            }}>
              <span style={{ fontSize: 12, lineHeight: 1 }}>+</span>
              {activeFilters.length === 0 ? "Filter by tag" : "Add"}
            </button>
            {tagDropdownOpen && <TagDropdown allTags={tagIndex} activeFilters={activeFilters} onAdd={addFilter} onClose={() => setTagDropdownOpen(false)} />}
          </div>
        )}

        <div style={{ flex: 1 }} />

        {/* Time range */}
        {!similarMode && (
          <div style={{ display: "flex", gap: 1, borderRadius: 6, overflow: "hidden", border: `1px solid ${c.border}` }}>
            {[["7d", "7d"], ["30d", "30d"], ["all", "All"]].map(([val, label]) => (
              <button key={val} onClick={() => setTimeRange(val)} style={{
                padding: "3px 9px", border: "none", fontSize: 10, fontFamily: font.sans,
                background: timeRange === val ? c.accentDim : c.bg,
                color: timeRange === val ? c.accent : c.textDim,
                cursor: "pointer", fontWeight: timeRange === val ? 600 : 400,
              }}>{label}</button>
            ))}
          </div>
        )}

        {/* Sort */}
        <div style={{ display: "flex", gap: 1, borderRadius: 6, overflow: "hidden", border: `1px solid ${c.border}` }}>
          {[["auto", "Auto"], ["date", "Date"], ["relevance", "Score"]].map(([val, label]) => (
            <button key={val} onClick={() => setSortMode(val)} style={{
              padding: "3px 9px", border: "none", fontSize: 10, fontFamily: font.sans,
              background: sortMode === val ? c.accentDim : c.bg,
              color: sortMode === val ? c.accent : c.textDim,
              cursor: "pointer", fontWeight: sortMode === val ? 600 : 400,
            }}>{label}{val === "auto" && <span style={{ fontSize: 8, opacity: 0.5, marginLeft: 2 }}>({isSearching ? "rel" : "date"})</span>}</button>
          ))}
        </div>

        {/* Result count + clear */}
        {hasActiveScope && (
          <>
            <span style={{ fontSize: 10, color: c.textMuted }}>{results.length} result{results.length !== 1 ? "s" : ""}</span>
            <button onClick={clearAll} style={{ padding: "2px 8px", borderRadius: 4, border: `1px solid ${c.border}`, background: "transparent", color: c.textMuted, fontSize: 10, fontFamily: font.sans, cursor: "pointer" }}>Clear</button>
          </>
        )}
      </div>

      {/* ─── Main: List + Reader ─────────────────── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* Document list */}
        <div style={{ width: 400, flexShrink: 0, borderRight: `1px solid ${c.border}`, display: "flex", flexDirection: "column", background: c.bg }}>

          {/* Search */}
          <div style={{ padding: "10px 14px", borderBottom: `1px solid ${c.border}` }}>
            <div style={{ position: "relative" }}>
              <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", fontSize: 13, color: c.textDim, pointerEvents: "none" }}>⌕</span>
              <input type="text" value={searchQuery}
                onChange={(e) => { setSearchQuery(e.target.value); if (similarMode) setSimilarMode(null); }}
                placeholder={activeFilters.length > 0 ? `Semantic search within ${results.length} docs...` : "Semantic search all documents..."}
                style={{ width: "100%", padding: "9px 12px 9px 32px", borderRadius: 8, border: `1px solid ${c.border}`, background: c.surface, color: c.text, fontSize: 13, fontFamily: font.sans, outline: "none" }}
                onFocus={(e) => e.target.style.borderColor = c.accent + "55"}
                onBlur={(e) => e.target.style.borderColor = c.border}
              />
              {isSearching && (
                <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", fontSize: 9, color: c.accent, background: c.accentDim, padding: "2px 6px", borderRadius: 3 }}>hybrid</span>
              )}
            </div>
          </div>

          {/* Results */}
          <div style={{ flex: 1, overflow: "auto" }}>
            {results.length === 0 ? (
              <div style={{ padding: 40, textAlign: "center" }}>
                <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.2 }}>∅</div>
                <div style={{ fontSize: 13, color: c.textMuted }}>No documents match</div>
                <div style={{ fontSize: 11, color: c.textDim, marginTop: 4 }}>Try broader terms or remove a filter</div>
              </div>
            ) : results.map((d) => {
              const isSelected = selectedDoc?.id === d.id;
              const visibleTags = d.tags.filter((t) => !activeFilters.includes(t));
              return (
                <div key={d.id} onClick={() => setSelectedDoc(d)}
                  style={{
                    padding: "12px 14px", borderBottom: `1px solid ${c.border}`,
                    borderLeft: `2px solid ${isSelected ? c.accent : "transparent"}`,
                    background: isSelected ? c.surfaceRaised : "transparent",
                    cursor: "pointer", transition: "all 0.08s",
                  }}
                  onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = `${c.surface}88`; }}
                  onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = "transparent"; }}
                >
                  <div style={{ display: "flex", alignItems: "start", gap: 8, marginBottom: 5 }}>
                    {d.score !== null && <ScoreBadge score={d.score} />}
                    <div style={{ flex: 1, fontSize: 13, fontWeight: isSelected ? 600 : 500, color: c.text, lineHeight: 1.4 }}>{d.title}</div>
                    <StatusDot status={d.status} />
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6, paddingLeft: d.score !== null ? 44 : 0 }}>
                    <span style={{ fontSize: 10, color: c.textDim }}>{d.type}</span>
                    <span style={{ fontSize: 10, color: c.textDim }}>·</span>
                    <span style={{ fontSize: 10, color: c.textDim }}>{d.source}</span>
                    <span style={{ fontSize: 10, color: c.textDim }}>·</span>
                    <span style={{ fontSize: 10, color: c.textDim }}>{timeAgo(d.date)}</span>
                  </div>
                  {visibleTags.length > 0 && (
                    <div style={{ display: "flex", gap: 3, flexWrap: "wrap", paddingLeft: d.score !== null ? 44 : 0 }}>
                      {visibleTags.slice(0, 4).map((t) => {
                        const isP = t.startsWith("project:");
                        const display = isP ? t.replace("project:", "") : t;
                        return (
                          <span key={t} onClick={(e) => { e.stopPropagation(); addFilter(t); }}
                            style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3, background: isP ? c.purpleDim : c.bg, color: isP ? c.purple : c.textMuted, border: `1px solid ${isP ? c.purple + "22" : c.border}`, cursor: "pointer", fontWeight: isP ? 600 : 400, transition: "all 0.1s" }}
                            onMouseEnter={(e) => { e.target.style.color = isP ? c.purple : c.accent; e.target.style.borderColor = (isP ? c.purple : c.accent) + "44"; }}
                            onMouseLeave={(e) => { e.target.style.color = isP ? c.purple : c.textMuted; e.target.style.borderColor = isP ? c.purple + "22" : c.border; }}
                          >{isP ? "⬡ " : ""}{display}</span>
                        );
                      })}
                      {visibleTags.length > 4 && <span style={{ fontSize: 9, color: c.textDim }}>+{visibleTags.length - 4}</span>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* ─── Reading Pane ──────────────────────── */}
        <div style={{ flex: 1, overflow: "auto", background: c.surface }}>
          {selectedDoc ? (
            <div style={{ padding: "28px 32px", maxWidth: 680 }}>
              {/* Header */}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <StatusBadge status={selectedDoc.status} />
                <span style={{ fontSize: 11, color: c.textDim }}>{selectedDoc.type}</span>
                <span style={{ color: c.textDim }}>·</span>
                <span style={{ fontSize: 11, color: c.textDim }}>{timeAgo(selectedDoc.date)}</span>
                {selectedDoc.score !== null && <>
                  <span style={{ color: c.textDim }}>·</span>
                  <ScoreBadge score={selectedDoc.score} />
                </>}
              </div>

              <h1 style={{ fontSize: 22, fontWeight: 700, fontFamily: font.serif, color: c.text, lineHeight: 1.35, margin: "0 0 12px" }}>{selectedDoc.title}</h1>

              <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: c.textMuted, marginBottom: 20 }}>
                <span>{selectedDoc.source}</span>
                <span style={{ color: c.textDim }}>·</span>
                <span style={{ fontFamily: font.mono, fontSize: 11, color: c.textDim }}>{selectedDoc.id}</span>
                <span style={{ color: c.textDim }}>·</span>
                <span>{selectedDoc.chunks} chunks</span>
              </div>

              {/* Tags */}
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 20, paddingBottom: 20, borderBottom: `1px solid ${c.border}` }}>
                {selectedDoc.tags.map((t) => {
                  const isP = t.startsWith("project:");
                  const display = isP ? t.replace("project:", "") : t;
                  return (
                    <span key={t} onClick={() => addFilter(t)} style={{
                      fontSize: 11, padding: "4px 10px", borderRadius: 6,
                      background: isP ? c.purpleDim : c.accentDim,
                      color: isP ? c.purple : c.accent,
                      border: `1px solid ${(isP ? c.purple : c.accent) + "33"}`,
                      cursor: "pointer", fontWeight: isP ? 600 : 400, transition: "all 0.1s",
                    }}
                      onMouseEnter={(e) => e.target.style.background = isP ? c.purple + "22" : c.accentMed}
                      onMouseLeave={(e) => e.target.style.background = isP ? c.purpleDim : c.accentDim}
                    >{isP ? "⬡ " : "#"}{display}</span>
                  );
                })}
              </div>

              {/* Content */}
              <div style={{ fontSize: 15, color: c.textSecondary, lineHeight: 1.8, fontFamily: font.serif, marginBottom: 28 }}>
                {selectedDoc.snippet}
              </div>

              {/* Actions */}
              <div style={{ display: "flex", gap: 8, marginBottom: 28 }}>
                <button onClick={() => handleFindSimilar(selectedDoc)} style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "8px 14px", borderRadius: 8,
                  border: `1px solid ${c.cyan}33`, background: c.cyanDim,
                  color: c.cyan, fontSize: 12, fontWeight: 500,
                  fontFamily: font.sans, cursor: "pointer", transition: "all 0.12s",
                }}
                  onMouseEnter={(e) => e.target.style.background = c.cyan + "22"}
                  onMouseLeave={(e) => e.target.style.background = c.cyanDim}
                >◎ Find Similar</button>
                <button style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "8px 14px", borderRadius: 8,
                  border: `1px solid ${c.border}`, background: "transparent",
                  color: c.textMuted, fontSize: 12, fontWeight: 500,
                  fontFamily: font.sans, cursor: "pointer",
                }}>🎧 Generate Audio</button>
              </div>

              {/* Chunks */}
              <div style={{ padding: "14px 18px", background: c.bg, borderRadius: 10, border: `1px solid ${c.border}`, marginBottom: 24 }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: c.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Chunks</div>
                <div style={{ display: "flex", gap: 3 }}>
                  {Array.from({ length: selectedDoc.chunks }).map((_, i) => (
                    <div key={i} style={{ flex: 1, height: 5, borderRadius: 3, background: i === 0 ? c.accent : c.border }} />
                  ))}
                </div>
                <div style={{ fontSize: 10, color: c.textDim, marginTop: 5 }}>{selectedDoc.chunks} chunks · embedded with BGE-small</div>
              </div>

              {/* Related via tag overlap */}
              {(() => {
                const related = docs.filter((d) => d.id !== selectedDoc.id && d.tags.some((t) => selectedDoc.tags.includes(t))).slice(0, 3);
                if (related.length === 0) return null;
                return (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: c.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Related by Tags</div>
                    {related.map((d) => (
                      <div key={d.id} onClick={() => setSelectedDoc({ ...d, score: null })}
                        style={{ padding: "9px 12px", borderRadius: 8, border: `1px solid ${c.border}`, marginBottom: 5, display: "flex", alignItems: "center", gap: 8, cursor: "pointer", transition: "background 0.1s" }}
                        onMouseEnter={(e) => e.currentTarget.style.background = c.surfaceHover}
                        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                      >
                        <StatusDot status={d.status} />
                        <div style={{ flex: 1, fontSize: 12, color: c.text, fontWeight: 500 }}>{d.title}</div>
                        <span style={{ fontSize: 10, color: c.textDim, fontFamily: font.mono }}>{d.id.slice(0, 8)}</span>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 32, opacity: 0.12 }}>📄</div>
              <div style={{ fontSize: 14, color: c.textDim }}>Select a document</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
