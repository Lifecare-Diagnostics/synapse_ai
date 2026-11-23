# Screens Documentation

## Dashboard
- **Purpose**: Provides a high-level overview of system usage and pipeline health.
- **Components**: Stat cards, Pipeline Health visualization, Recent Uploads table.
- **Mock Data**: High-level counts, and a table showing recent reports for Patients Alpha and Beta.

## Upload
- **Purpose**: Facilitates ingestion of new reports across multiple formats (Digital PDF, Scanned PDF with OCR, Medical Images, and Narrative Clinical Notes).
- **Components**: Drag-and-drop zone, format simulation switcher (Digital PDF, Scanned OCR, Image OCR, Clinical Note LLM), processing step tracker, and review queue transition button.
- **Mock Data**: Simulations for 'CBC_report.pdf' (Digital), 'scanned_lipid_profile.pdf' (OCR), 'biochemistry_slip.png' (Image OCR), and 'dr_sharma_clinical_note.txt' (LLM).

## Review
- **Purpose**: Human-in-the-loop validation of AI-extracted data against the original report.
- **Components**: Split view, mock CSS report rendering, editable validation table, toast notification.
- **Mock Data**: Patient Alpha's CBC report from Mar 2024.

## Report Library
- **Purpose**: Comprehensive search and filtering of all ingested reports.
- **Components**: Filter dropdowns, search bar, results table, status chips.
- **Mock Data**: Historic reports for Patient Alpha.

## Patient Timeline
- **Purpose**: Chronological history of a specific patient with visual trends.
- **Components**: Vertical timeline, SVG line chart for Hemoglobin levels.
- **Mock Data**: Patient Alpha's historic Hemoglobin levels over time.

## AI Assistant
- **Purpose**: Natural language querying over retrieved structured data with clinical summaries.
- **Components**: Chat interface, response summary card, retrieved data panel.
- **Mock Data**: AI-generated summary of Patient Alpha's Hemoglobin history.
