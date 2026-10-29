# Flow Mapping

This table maps each UI screen to the Synapse flow stages.

| Screen | Flow Stage(s) | Description |
|--------|--------------|-------------|
| **Dashboard** | 5. Structured Database | Aggregates data from the database to show ingestion and processing metrics. |
| **Upload** | 1. Ingestion, 2. Detect Format, 3. Extract | Handles the initial upload, format detection, and AI extraction process. |
| **Review** | 4. Validate | The core interface for human review and schema checks before data is committed. |
| **Report Library** | 7. Search | Interface to search and filter through the structured database. |
| **Patient Timeline** | 6. Chronological History | Organizes and visualizes the structured data chronologically. |
| **AI Assistant** | 8. AI Layer | Interprets and summarizes retrieved data for the clinician. |
