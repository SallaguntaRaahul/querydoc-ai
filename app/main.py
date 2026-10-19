"""QueryDoc AI — Streamlit interface.

Run:  streamlit run app/main.py
Author: Raahul Sallagunta
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import querydoc  # noqa: E402,F401  (OpenMP guard before torch/faiss)
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.components.viewer import render_page  # noqa: E402
from querydoc.config import get_settings  # noqa: E402
from querydoc.exceptions import QueryDocError  # noqa: E402
from querydoc.generation.llm import GenerationParams  # noqa: E402
from querydoc.services.rag_service import QueryDocService, RAGResponse, rss_mb  # noqa: E402

st.set_page_config(page_title="QueryDoc AI", page_icon="📄", layout="wide")


@st.cache_resource(show_spinner="Loading embedding model and index…")
def get_service() -> QueryDocService:
    """One service (models + index) per server process, shared across reruns and sessions."""
    return QueryDocService(get_settings())


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("history", [])  # list[RAGResponse]
    ss.setdefault("ingest_log", [])  # list[dict]
    ss.setdefault("viewer", None)  # (doc_id, page, excerpt)


STATUS_BADGE = {
    "verified": ":green-badge[Verified citations]",
    "partially_verified": ":orange-badge[Partially verified]",
    "unverified": ":red-badge[Could not verify]",
    "insufficient_evidence": ":gray-badge[Insufficient evidence]",
    "retrieval_only": ":blue-badge[Retrieval only]",
}


# ---------------------------------------------------------------- sidebar
def sidebar(svc: QueryDocService) -> dict:
    s = svc.settings
    st.sidebar.title("📄 QueryDoc AI")
    st.sidebar.caption("Local PDF retrieval-augmented generation")
    docs = svc.documents()
    with st.sidebar.expander("Advanced settings", expanded=False):
        st.markdown("**Ingestion** (applies to new uploads)")
        chunk_size = st.slider("Chunk size (chars)", 200, 1500, s.chunk_size, 50)
        chunk_overlap = st.slider("Chunk overlap (chars)", 0, 400, min(s.chunk_overlap, chunk_size - 50), 10)
        batch = st.select_slider("Embedding batch size", [1, 8, 16, 32, 64, 128], value=s.embedding_batch_size)
        st.markdown("**Retrieval**")
        top_k = st.slider("Top-k passages", 1, 10, s.top_k)
        use_hybrid = st.toggle("Hybrid BM25 + dense", value=s.use_hybrid)
        use_rerank = st.toggle("Cross-encoder reranking", value=s.use_rerank)
        use_mmr = st.toggle("MMR diversification", value=s.use_mmr)
        st.markdown("**Generation**")
        generate = st.toggle("Generate answer with local LLM", value=True)
        max_tokens = st.slider("Max new tokens", 32, 512, s.max_new_tokens, 16)
        temperature = st.slider("Temperature", 0.0, 1.0, s.temperature, 0.05)
        st.caption(f"Model: `{s.llm_model}` · device `{s.llm_device}`")
        st.caption(f"Embeddings: `{s.embedding_model}` on `{svc.embedder.device}`")
    selected = st.sidebar.multiselect(
        "Search within",
        options=[d.doc_id for d in docs],
        default=[d.doc_id for d in docs],
        format_func=lambda i: next((d.filename for d in docs if d.doc_id == i), i),
    )
    st.sidebar.divider()
    st.sidebar.caption("Author: **Raahul Sallagunta**")
    return dict(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, batch=batch, top_k=top_k,
        use_hybrid=use_hybrid, use_rerank=use_rerank, use_mmr=use_mmr, generate=generate,
        max_tokens=max_tokens, temperature=temperature, selected=selected,
    )


# ------------------------------------------------------------- workspace
def workspace_tab(svc: QueryDocService, opts: dict) -> None:
    st.subheader("Document workspace")
    files = st.file_uploader(
        f"Upload PDFs (max {svc.settings.max_upload_mb:.0f} MB, {svc.settings.max_pages} pages each)",
        type=["pdf"], accept_multiple_files=True,
    )
    if files and st.button(f"Process {len(files)} file(s)", type="primary"):
        cfg = svc.chunking_config(chunk_size=opts["chunk_size"], chunk_overlap=opts["chunk_overlap"])
        for f in files:
            bar = st.progress(0.0, text=f"{f.name}: starting")

            def progress(stage: str, frac: float, _bar=bar, _name=f.name) -> None:
                _bar.progress(min(frac, 1.0), text=f"{_name}: {stage} {frac:.0%}")

            try:
                rep = svc.ingest(f.getvalue(), f.name, chunking=cfg, batch_size=opts["batch"], progress=progress)
                r = rep.record
                msg = f"✅ {r.filename}: {r.page_count} pages → {r.chunk_count} chunks"
                if r.scanned_pages:
                    msg += f" · ⚠️ {len(r.scanned_pages)} page(s) look scanned (OCR disabled, not indexed)"
                st.success(msg)
                st.session_state.ingest_log.append(
                    {"file": r.filename, **{f"{k}_ms": round(v, 1) for k, v in rep.timings_ms.items()},
                     "chunks/s": round(rep.embedding["chunks_per_second"], 1),
                     "cache_hit_rate": round(rep.embedding["cache_hit_rate"], 2),
                     "rss_mb_after": round(rep.rss_mb_after, 1)}
                )
            except QueryDocError as exc:
                bar.empty()
                st.error(f"❌ {f.name}: {exc}")

    docs = svc.documents()
    if not docs:
        st.info("No documents yet. Upload one or more PDFs to build the index.")
        return
    st.markdown(f"**{len(docs)} document(s) · {svc.store.size} indexed chunks · index type `{svc.store.index_type}`**")
    for d in docs:
        c1, c2, c3, c4, c5 = st.columns([4, 1, 1, 2, 1])
        c1.markdown(f"**{d.filename}**  \n`{d.doc_id}` · {d.title[:60]}")
        c2.metric("Pages", d.page_count)
        c3.metric("Chunks", d.chunk_count)
        c4.caption(
            f"Embedded ✓ · Indexed ✓  \nchunking: {d.chunking.get('strategy')} "
            f"{d.chunking.get('chunk_size')}/{d.chunking.get('chunk_overlap')}"
            + (f"  \n⚠️ scanned pages: {d.scanned_pages[:10]}" if d.scanned_pages else "")
        )
        if c5.button("Delete", key=f"del-{d.doc_id}"):
            svc.delete_document(d.doc_id)
            st.rerun()


# ------------------------------------------------------------------- chat
def run_query(svc: QueryDocService, question: str, opts: dict) -> RAGResponse:
    cfg = svc.retrieval_config(
        top_k=opts["top_k"], use_hybrid=opts["use_hybrid"], use_rerank=opts["use_rerank"],
        use_mmr=opts["use_mmr"], doc_ids=opts["selected"],
    )
    params = GenerationParams(max_new_tokens=opts["max_tokens"], temperature=opts["temperature"])
    return svc.answer(question, cfg, params, generate=opts["generate"])


def show_response(resp: RAGResponse, idx: int) -> None:
    st.markdown(STATUS_BADGE.get(resp.status, ""))
    if resp.answer:
        st.markdown(resp.answer)
    for note in resp.notes:
        st.caption(f"ℹ️ {note}")
    t = resp.timings_ms
    st.caption(
        f"retrieval {t.get('retrieval', 0):.0f} ms · generation {t.get('generation', 0):.0f} ms · "
        f"total {t.get('total', 0):.0f} ms"
        + (f" · {resp.generation.completion_tokens} tokens @ {resp.generation.tokens_per_second:.1f} tok/s"
           if resp.generation else "")
    )
    cites = resp.citations.citations if resp.citations else []
    if cites:
        st.markdown("**Sources**")
        for c in cites:
            col1, col2 = st.columns([5, 1])
            col1.markdown(f"**[{c.tag}]** {c.source} · {c.pages_label} · `{c.chunk_id}`  \n> {c.excerpt}")
            if col2.button("Open page", key=f"open-{idx}-{c.tag}"):
                st.session_state.viewer = (c.doc_id, c.page_start, c.excerpt)
                st.toast(f"Showing {c.source} {c.pages_label} in Source Explorer")
    elif resp.retrieval.chunks:
        with st.expander("Retrieved passages", expanded=resp.mode == "retrieval_only"):
            for r in resp.retrieval.chunks:
                st.markdown(f"**#{r.rank}** {r.chunk.source} · {r.chunk.pages_label} · score {r.score:.3f}")
                st.text(r.chunk.text[:600])
                if st.button("Open page", key=f"open-{idx}-r{r.rank}"):
                    st.session_state.viewer = (r.chunk.doc_id, r.chunk.page_start, r.chunk.text[:120])


def chat_tab(svc: QueryDocService, opts: dict) -> None:
    st.subheader("Ask your documents")
    if not svc.documents():
        st.info("Upload a document in the Workspace tab first.")
    for i, resp in enumerate(st.session_state.history):
        with st.chat_message("user"):
            st.markdown(resp.question)
        with st.chat_message("assistant"):
            show_response(resp, i)
    question = st.chat_input("Ask a question about the selected PDFs…")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            spinner = "Retrieving and generating (first answer loads the local model)…" if opts["generate"] else "Retrieving…"
            try:
                with st.spinner(spinner):
                    resp = run_query(svc, question, opts)
                st.session_state.history.append(resp)
                show_response(resp, len(st.session_state.history) - 1)
            except QueryDocError as exc:
                st.error(str(exc))
    if st.session_state.history and st.button("Clear conversation"):
        st.session_state.history = []
        st.rerun()


# --------------------------------------------------------- source explorer
def sources_tab(svc: QueryDocService) -> None:
    st.subheader("Source explorer")
    viewer = st.session_state.viewer
    if viewer:
        doc_id, page, excerpt = viewer
        rec = svc.registry.get(doc_id)
        if rec and svc.document_path(doc_id).exists():
            st.markdown(f"**{rec.filename} — page {page}** (highlighted: cited excerpt)")
            nav1, nav2, _ = st.columns([1, 1, 6])
            if nav1.button("◀ Prev", disabled=page <= 1):
                st.session_state.viewer = (doc_id, page - 1, excerpt)
                st.rerun()
            if nav2.button("Next ▶", disabled=page >= rec.page_count):
                st.session_state.viewer = (doc_id, page + 1, excerpt)
                st.rerun()
            st.image(render_page(svc.document_path(doc_id), page, excerpt), width="stretch")
    if not st.session_state.history:
        st.info("Ask a question to see the passages retrieved for it.")
        return
    last = st.session_state.history[-1]
    st.markdown(f"Passages retrieved for: _{last.question}_")
    rows = [
        {
            "rank": r.rank, "source": r.chunk.source, "pages": r.chunk.pages_label, "chunk_id": r.chunk.chunk_id,
            "final_score": round(r.score, 4),
            **{k: round(v, 4) for k, v in r.scores.items()},
            "excerpt": r.chunk.text[:160].replace("\n", " "),
        }
        for r in last.retrieval.chunks
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ------------------------------------------------------------ performance
def perf_tab(svc: QueryDocService) -> None:
    st.subheader("Performance (measured in this session)")
    c1, c2, c3 = st.columns(3)
    c1.metric("Process RSS", f"{rss_mb():.0f} MB")
    c2.metric("Indexed chunks", svc.store.size)
    c3.metric("Approx. index memory", f"{svc.store.memory_bytes() / 1024**2:.1f} MB")
    log = st.session_state.ingest_log
    st.markdown("**Ingestion timings**")
    if log:
        st.dataframe(pd.DataFrame(log), hide_index=True, width="stretch")
    else:
        st.caption("No uploads processed in this session yet.")
    hist = st.session_state.history
    st.markdown("**Query timings**")
    if hist:
        df = pd.DataFrame(
            [{"question": h.question[:60], **{f"{k}_ms": round(v, 1) for k, v in h.timings_ms.items()},
              "tokens": h.generation.completion_tokens if h.generation else None} for h in hist]
        )
        st.dataframe(df, hide_index=True, width="stretch")
        st.bar_chart(df.set_index("question")[[c for c in ("retrieval_ms", "generation_ms") if c in df]])
    else:
        st.caption("No queries yet.")
    st.caption("Reproducible benchmark results live in `results/` and `docs/PERFORMANCE_REPORT.md`.")


def main() -> None:
    init_state()
    try:
        svc = get_service()
    except QueryDocError as exc:
        st.error(f"Could not start: {exc}")
        st.stop()
    opts = sidebar(svc)
    st.title("QueryDoc AI")
    st.caption("Ask questions about your PDFs. Answers are generated locally and cite the exact pages they come from.")
    tabs = st.tabs(["💬 Ask", "📁 Workspace", "🔎 Source explorer", "📊 Performance"])
    with tabs[0]:
        chat_tab(svc, opts)
    with tabs[1]:
        workspace_tab(svc, opts)
    with tabs[2]:
        sources_tab(svc)
    with tabs[3]:
        perf_tab(svc)
    st.divider()
    st.caption("QueryDoc AI · Author: Raahul Sallagunta · runs fully on this machine")


main()
