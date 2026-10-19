"""Generate deterministic PDFs used by the Playwright suite (run by global-setup)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from querydoc.evaluation.synthetic import make_synthetic_pdf  # noqa: E402

out = Path(__file__).resolve().parent / "fixtures"
out.mkdir(exist_ok=True)
long_name = "Quarterly-operations-handbook-for-regional-supply-chain-and-warehouse-safety-compliance-programmes-2026-edition.pdf"
data, _ = make_synthetic_pdf(6, seed=401, title="An exceptionally long document title used to check truncation in cards and headers")
(out / long_name).write_bytes(data)
for i in range(10):
    data, _ = make_synthetic_pdf(3, seed=500 + i, title=f"Collection manual {i + 1}")
    (out / f"collection-manual-{i + 1:02d}.pdf").write_bytes(data)
(out / "not-a-pdf.pdf").write_bytes(b"This is plain text pretending to be a PDF.")
print(f"fixtures written to {out}")
