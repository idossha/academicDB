# Academic DB

Simple Postgres + Python ingestion for academic paper metadata.

## Quick start

1. Start Postgres with Docker:
   - `docker compose up -d`
2. Install Python dependencies (uv):
   - `uv venv`
   - `source .venv/bin/activate`
   - `uv sync`
3. Ingest PDFs from a directory:
   - `python ingest_papers.py /path/to/papers --recursive`

## Configuration

Database defaults match `docker-compose.yml` (Postgres exposed on `5433` to avoid local conflicts). Override with env vars if needed:

- `DB_HOST` (default: `localhost`)
- `DB_PORT` (default: `5433`)
- `DB_NAME` (default: `academic`)
- `DB_USER` (default: `academic`)
- `DB_PASSWORD` (default: `academic`)
- `GROBID_URL` (default: `http://localhost:8070`)

## Data model

`db/init.sql` creates a `papers` table with:

- `file_path` (unique)
- `title`
- `document_type`
- `publication_date`
- `journal_title`
- `book_title`
- `publisher`
- `authors` (text array)
- `affiliations` (text array)
- `countries` (text array)
- `abstract`
- `year`
- `keywords` (text array)
- `raw_text_snippet` (first 500 chars for debugging)
- `processed_at` (ingestion timestamp)

## Notes

- If GROBID is running, metadata extraction uses it first, then falls back to heuristics.
- Keyword parsing falls back to `Keywords:` or `Index Terms:` in the first pages.
- When only a year/month is available, `publication_date` is set to the first day of the month/year.
- After schema changes, recreate the DB with `docker compose down -v && docker compose up -d`.

## Daily cron on Raspberry Pi

1. Make the script executable:
   - `chmod +x scripts/ingest_daily.sh`
2. Edit your crontab:
   - `crontab -e`
3. Add these lines to run at 4am daily and backup at 4:05:
   - `0 4 * * * PAPERS_DIR="/path/to/papers" /bin/bash /path/to/academic-db/scripts/ingest_daily.sh >> /path/to/academic-db/ingest.log 2>&1`
   - `5 4 * * * BACKUP_DIR="/path/to/backups" /bin/bash /path/to/academic-db/scripts/backup_daily.sh >> /path/to/academic-db/backup.log 2>&1`
