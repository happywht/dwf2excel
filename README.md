# DWF2Excel

A Python desktop utility for working with CAD drawing data and spreadsheet reports. The application is organized around drawing parsing and writing, a processing pipeline, Excel reporting, and a graphical interface.

## Capabilities

- Parse supported CAD drawing entities and annotations.
- Prepare structured spreadsheet reports with pandas and openpyxl.
- Run a desktop interface for the extraction and reporting workflow.
- Write supported data changes back to drawings.

Supported formats and write-back behavior depend on the current parser and writer implementation. Please verify your files on copies before using write-back, and report unsupported entities with a sanitized sample.

## Requirements

- Python 3.10 or newer (recommended)
- Dependencies listed in `requirements.txt`

## Run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Project structure

- `core/` — drawing parsing, models, processing pipeline, and spreadsheet reporting
- `gui/` — desktop application interface
- `config/` — application settings
- `utils/` — shared helpers

## Related projects

- [CAD Intelligent Extraction Platform](https://github.com/happywht/cadzhinengduqu_pingtai)
- [AI Invoice OCR](https://github.com/happywht/ai_ocr_version01)

## Development status

The repository is maintained as a public engineering utility. Format coverage, edge cases, and safe write-back behavior should be validated against representative drawings before production use. Please open an issue with a minimal, sanitized example when you find a problem.
