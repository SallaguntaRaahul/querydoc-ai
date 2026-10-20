# Third-party notices

QueryDoc AI's own source code is MIT-licensed (see `LICENSE`). It depends on third-party
software and models that keep their own licenses; they are installed by the package managers
and are not redistributed in this repository.

| Component | License | Note |
|---|---|---|
| PyMuPDF / MuPDF | AGPL-3.0 (or Artifex commercial license) | If you distribute or offer a modified version of a product built on QueryDoc AI as a network service, AGPL obligations apply to PyMuPDF; obtain a commercial license or replace the PDF library for closed-source distribution. |
| FAISS | MIT | |
| PyTorch | BSD-3-Clause | |
| Hugging Face Transformers, sentence-transformers | Apache-2.0 | |
| LangChain (core, text-splitters) | MIT | |
| FastAPI, Starlette, Pydantic, Uvicorn, SQLAlchemy, Alembic | MIT / BSD | |
| rank-bm25 | Apache-2.0 | |
| React, Vite, TanStack Query, React Router, Recharts, Zod, React Hook Form, Motion, Lucide | MIT / ISC | |
| Radix UI, shadcn/ui (copied components) | MIT | |
| react-pdf (MIT), PDF.js (Apache-2.0) | MIT / Apache-2.0 | |
| Tailwind CSS | MIT | |
| Geist font | SIL Open Font License 1.1 | |
| Qwen2.5-0.5B/1.5B-Instruct | Apache-2.0 | downloaded at runtime |
| all-MiniLM-L6-v2, ms-marco-MiniLM-L-6-v2 | Apache-2.0 | downloaded at runtime |
| NIST publications (evaluation corpus) | U.S. government works (17 U.S.C. §105) | downloaded by `scripts/download_corpus.py`, not stored in git |
