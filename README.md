# Mistral OCR Application

Streamlit app for OCR using Mistral AI. Convert PDFs and images to markdown with LaTeX support, smart exports, and session management.

## Features

- **High-accuracy OCR**: Handles messy fonts, tables, math equations (LaTeX), and code blocks
- **AI-powered filenames**: OpenAI GPT-4o-mini generates descriptive names from content
- **Multiple exports**: PDF, HTML (with LaTeX), or Markdown with page range selection
- **Export history**: View, download, or batch delete exports per session
- **Session management**: Work on multiple documents with independent caches
- **Three-column UI**: PDF preview | Rendered markdown | Raw editor

## Setup

```powershell
git clone https://github.com/tanhg1116/Clipboard-Mistral-OCR.git
cd Clipboard-Mistral-OCR
pip install -r requirements.txt

# Add API keys to .env
copy .env.example .env
# MISTRAL_API_KEY=your_key_here
# OPENAI_API_KEY=your_key_here  # Optional

streamlit run app.py
```

**API Keys:**
- [Mistral](https://admin.mistral.ai/organization/api-keys) - Required for OCR
- [OpenAI](https://platform.openai.com/api-keys) - Optional for smart filenames

## Export Formats

- **PDF**: Direct generation (no LaTeX support)
- **HTML**: Full LaTeX rendering, print to PDF via browser
- **Markdown**: Plain text, preserves all formatting

⚠️ **For documents with equations**: Use HTML export, then Print → Save as PDF in browser.

## Dependencies

Core: `streamlit`, `mistralai`, `openai`, `python-dotenv`  
Document: `PyMuPDF`, `PyPDF2`, `Pillow`, `pyperclip`  
Export: `nbformat`, `nbconvert`, `markdown-pdf`, `markdown`  
Testing: `pytest`

## Contributing

Contributions welcome! Please:
1. Open an issue to discuss proposed changes
2. Fork the repository
3. Create a feature branch
4. Submit a pull request with clear description

## Troubleshooting

**PDF export without LaTeX support?** Export as HTML, then Print → Save as PDF in browser.

**Missing API key?** Check `.env` has `MISTRAL_API_KEY=...` (OpenAI key optional)

**Clipboard paste not working?** `pip install Pillow --upgrade`

## License

MIT License