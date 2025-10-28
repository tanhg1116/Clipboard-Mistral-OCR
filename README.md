# Mistral OCR Quickstart

Struggling because you just screenshotted unselectable text, don’t want to spin up a Python script or burn ChatGPT quota for a quick OCR job? This Streamlit app runs Mistral’s OCR ($1 per 1,000 pages) on PDFs and images fast—upload or paste, edit the markdown, then copy or export it.

## Run It

```powershell
pip install -r requirements.txt
copy .env.example .env   # fill in MISTRAL_API_KEY
# Grab a key from https://admin.mistral.ai/organization/api-keys and paste it into .env
streamlit run app.py
```

## Use It

1. Drop in a PDF or image, or hit “Paste image from clipboard”.
2. Switch between uploaded files with the dropdown; each file keeps its own OCR results and edits.
3. Edit the markdown, copy it with one click, or export selected pages to PDF/Markdown.
4. Spin up multiple tasks with the session sidebar; exports keep running while you work.

### Why Mistral OCR?
- **High accuracy**: The vision-language model handles messy fonts and mixed layouts better than traditional OCR engines.
- **Math friendly**: It understands LaTeX-style notation, returning Markdown math blocks instead of mangled symbols.
- **Structure aware**: Tables, lists, and code snippets come back as well-formed Markdown, preserving the original layout.

## Tests

```powershell
pytest
```
