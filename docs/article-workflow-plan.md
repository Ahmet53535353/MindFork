# MindFork (Beyin) — Article Fetching & Analysis Workflow Integration Plan

## Overview
Add a structured article collection and analysis pipeline to the Beyin vault:
- Fetch articles via Firecrawl (clean, ad-free, HTML-error-free)
- Store as `k-YYYYMMDD-topic-slug.md` in `articles/` folder
- AI analysis: summary + project applicability mapping
- Integrate with existing hook/sync/receipt system

---

## 1. Vault Structure Changes

### New Directories
```
~/Documents/Beyin/
├── articles/                    # Raw fetched articles
│   ├── k-20240115-ai-trends.md
│   └── k-20240116-rust-async.md
├── articles/processed/          # AI-analyzed versions (JSON + markdown)
│   └── k-20240115-ai-trends.analysis.json
├── articles/index/              # Search index files
│   └── articles-index.json
├── knowledge/projects/          # Project registry for matching
│   ├── beyin-v3.md
│   ├── mindfork-core.md
│   └── other-projects.md
└── daily/v3/                    # Already exists (auto-generated from receipts)
```

### File Naming Convention
- **Raw**: `k-YYYYMMDD-topic-slug.md` (lowercase, ASCII, hyphens)
- **Processed**: `k-YYYYMMDD-topic-slug.analysis.json`
- **Index**: `articles/index/articles-index.json`

---

## 2. Firecrawl Integration

### New Skill: `articles-fetch`
Location: `.agents/skills/articles-fetch/SKILL.md`

**Commands:**
```bash
# Search + fetch articles on topic
firecrawl search "AI agents 2024" --scrape --limit 5 -o articles/search-results.json

# Fetch specific URLs
firecrawl scrape "https://example.com/article" -o articles/k-20240115-topic.md

# Batch fetch from search results
firecrawl scrape "url1,url2,url3" -o articles/batch.md
```

**Prerequisites:**
- `FIRECRAWL_API_KEY` environment variable
- Skill loads `firecrawl` skill as dependency

### Configuration
```bash
# Add to shell profile
export FIRECRAWL_API_KEY="fc-..."
```

---

## 3. AI Analysis Pipeline

### New Skill: `articles-analyze`
Location: `.agents/skills/articles-analyze/SKILL.md`

**Input:** Raw article markdown in `articles/k-*.md`
**Output:** Analysis JSON in `articles/processed/k-*.analysis.json`

**Analysis Fields:**
```json
{
  "article_id": "k-20240115-ai-trends",
  "source_url": "https://...",
  "fetched_at": "2024-01-15T10:30:00Z",
  "summary": "2-3 paragraph summary",
  "key_concepts": ["concept1", "concept2"],
  "technical_details": ["detail1", "detail2"],
  "actionable_insights": ["insight1", "insight2"],
  "project_matches": [
    {"project": "beyin-v3", "relevance": "high", "applicable_areas": ["consolidation", "hooks"]},
    {"project": "mindfork-core", "relevance": "medium", "applicable_areas": ["architecture"]}
  ],
  "quality_score": 0.85,
  "tags": ["ai", "agents", "architecture"]
}
```

**Prompt Template:**
```
Analyze this article for a technical knowledge management system.
Extract: summary, key concepts, technical details, actionable insights.
Match against these projects: [project list from knowledge/projects/]
Return JSON with project_matches array containing project, relevance (high/medium/low), applicable_areas.
```

---

## 4. Project Registry System

### `knowledge/projects/` Structure
Each project file:
```markdown
---
type: semantic
project: MindFork
visibility: internal
---

# Project: Beyin V3
**Status:** Active
**Description:** Second brain / companion system with memory engineering
**Technologies:** Python, Markdown, SQLite, Hooks
**Areas:**
- Memory consolidation (episodic/semantic/procedural)
- Hook-based lifecycle (SessionStart/End)
- Receipt-driven daily logs
- Skill system
**Current Focus:** Consolidation skill, Daily log integration, Explicit memory typing
**Keywords:** memory, consolidation, hooks, receipts, skills, AI companion
```

### Project Matching Algorithm
1. Load all `knowledge/projects/*.md`
2. Extract keywords, areas, technologies
3. Compare with article analysis `key_concepts` + `technical_details`
4. Score relevance: high (>3 matches), medium (1-2), low (0 but related domain)
5. Output `project_matches` in analysis JSON

---

## 5. Hook Integration (`SessionEnd`)

### Extended `drain_queue()` in `beyin_v3_hook.py`

```python
# After successful sync, add article processing:
if result.get("status") in ("succeeded", "synced"):
    # 1. Daily log append (existing)
    append_daily_log(vault, session_summary)
    
    # 2. Receipt creation (existing)
    if session_event_id:
        create_receipt(...)
    
    # 3. NEW: Article fetch queue processing
    if has_pending_article_fetches(state):
        process_article_queue(vault, state)
    
    # 4. Consolidation check (existing)
    if should_run_consolidation(state):
        run_consolidation_subagent(vault, state)
```

### Article Queue Processing
- Store pending fetch requests in `state/article-queue/*.json`
- Worker processes queue asynchronously
- Each fetch → save to `articles/` → queue analysis
- Analysis → save to `articles/processed/` → update index

---

## 6. CLI Commands (via `beyin.py`)

### New Commands
```bash
# Fetch articles on topic
python3 beyin.py articles-fetch "topic" --limit 5

# Analyze all unprocessed articles
python3 beyin.py articles-analyze

# Show project matches for article
python3 beyin.py articles-match "k-20240115-ai-trends"

# List articles with project applicability
python3 beyin.py articles-list --project beyin-v3

# Search articles by concept
python3 beyin.py articles-search "consolidation"
```

### Implementation
Add subcommands to `beyin_v3_cli.py`:
- `articles-fetch` → calls firecrawl, saves to `articles/`
- `articles-analyze` → runs AI analysis on unprocessed
- `articles-match` → reads analysis, shows project matches
- `articles-list` → queries `articles/index/articles-index.json`

---

## 7. Sync System Integration

### New Source Types for `beyin_v3_sync.py`
```python
# Article sources are semantic notes with special metadata
ALLOWED_ARTICLE_PATHS = (
    'articles/',           # raw
    'articles/processed/', # analyzed
    'articles/index/',     # index
)

# In note_create validation:
if source.startswith('articles/'):
    require_type = 'semantic'  # articles are semantic knowledge
    require_fields = ['source_url', 'fetched_at', 'quality_score']
```

### Index Updates
- `articles/index/articles-index.json` updated on each fetch/analyze
- Format: array of article metadata for fast search
- Used by `articles-list` and `articles-search` commands

---

## 8. Consolidation Integration

### Article-Specific Consolidation Rules
| Age | Action |
|-----|--------|
| >30 days | Compress: keep summary + project_matches, drop full text |
| >90 days | Archive: move to `articles/archive/` with zip |

### Re-index Phase
- Rebuild `articles-index.json` from all `articles/processed/*.analysis.json`
- Update project match cache

---

## 9. Implementation Phases

### Phase 1: Foundation (Week 1)
- [ ] Create `articles/`, `articles/processed/`, `articles/index/` directories
- [ ] Create `knowledge/projects/` with current projects
- [ ] Write `articles-fetch` skill (wraps firecrawl)
- [ ] Add `articles-fetch` CLI command

### Phase 2: Analysis Pipeline (Week 1-2)
- [ ] Write `articles-analyze` skill
- [ ] Add `articles-analyze` CLI command
- [ ] Implement project matching algorithm
- [ ] Create `articles-index.json` builder

### Phase 3: Hook Integration (Week 2)
- [ ] Extend `drain_queue()` in `beyin_v3_hook.py`
- [ ] Add article queue in `state/article-queue/`
- [ ] Background worker for fetch → analyze pipeline
- [ ] SessionEnd auto-trigger

### Phase 4: Query & Discovery (Week 2-3)
- [ ] Add `articles-match`, `articles-list`, `articles-search` commands
- [ ] Integrate with `beyin.py context` for retrieval
- [ ] Add article references to daily log / receipts

### Phase 5: Polish (Week 3)
- [ ] Consolidation rules for articles
- [ ] Quality scoring & duplicate detection
- [ ] Documentation in `knowledge/concepts/articles-workflow.md`
- [ ] Tests & verification

---

## 10. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `k-` prefix | Distinguishes from user notes, sortable by date |
| Separate `processed/` | Raw preserved; analysis is derived, regeneratable |
| Project registry in `knowledge/projects/` | Semantic, queryable, version-controlled |
| Hook-driven async processing | Non-blocking; fits existing SessionEnd pattern |
| Firecrawl skill as dependency | Reuses existing global install; no new deps |
| Analysis as JSON | Structured for programmatic matching |

---

## 11. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| API costs (Firecrawl credits) | Limit default fetch count; add `--limit` flag; track in analysis |
| Duplicate articles | URL-based dedup in index; checksum comparison |
| Analysis quality variance | Quality score threshold; manual review flag |
| Large article volume | Consolidation prune; archive old raw files |
| Hook timeout | Async worker; queue in state, not hook context |

---

## 12. Files to Create/Modify

### New Files
```
.agents/skills/articles-fetch/SKILL.md
.agents/skills/articles-analyze/SKILL.md
knowledge/projects/beyin-v3.md
knowledge/projects/mindfork-core.md
knowledge/concepts/articles-workflow.md
.claude/scripts/beyin_v3_articles.py          # Core logic
```

### Modified Files
```
beyin_v3_cli.py          # Add articles-* subcommands
beyin_v3_sync.py         # Allow articles/ sources, add index logic
beyin_v3_hook.py         # Extend drain_queue() for article queue
knowledge/index.md       # Add articles workflow entry
```

---

## 13. Verification Checklist

- [ ] `firecrawl search "test" --limit 1` works with API key
- [ ] Article saved to `articles/k-YYYYMMDD-topic.md` with frontmatter
- [ ] `articles-analyze` produces valid JSON with project_matches
- [ ] `articles-match` shows correct project relevance
- [ ] `articles-list --project beyin-v3` filters correctly
- [ ] SessionEnd hook processes article queue without blocking
- [ ] Consolidation prunes/compresses old articles
- [ ] All new skills pass `beyin.py doctor`
- [ ] Receipt references article sources correctly

---

## 14. Next Steps

1. **Confirm**: Review this plan; adjust scope/priorities
2. **Approve**: Give go-ahead for Phase 1 implementation
3. **Detail**: Define exact project registry content (I can draft from current knowledge)
4. **Iterate**: Start with Phase 1, verify each step before proceeding

---

*Plan created: 2026-09-23*
*Target integration: MindFork (Beyin v3)*
