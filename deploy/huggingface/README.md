---
title: QueryDoc AI
emoji: 📄
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Ask questions about your PDFs and get cited answers
---

# QueryDoc AI

Upload PDFs and ask questions about them. Answers come from an open-source model
(Qwen2.5-1.5B-Instruct) running inside this Space. Every claim links to the page it
came from.

- **Private accounts:** your documents and conversations are visible only to you.
  You can delete your account and all its data at any time.
- **Free CPU hardware:** search takes well under a second. Generated answers take
  roughly 30–90 seconds because there is no GPU. Only one answer is generated at a
  time, so you may wait in a short queue.
- **Limits:** 20 documents and 200 MB per account, 20 MB and 400 pages per PDF.
  There is no password reset.
- After 48 hours without visitors the Space sleeps. The next visit wakes it in a
  minute or two, and accounts and documents are kept.

For the best experience open the app directly at the `*.hf.space` address, not
inside the Hugging Face page.

Source code, benchmarks and documentation:
[github.com/SallaguntaRaahul/querydoc-ai](https://github.com/SallaguntaRaahul/querydoc-ai) · MIT License ·
Built by Raahul Sallagunta
