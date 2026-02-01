import argparse
import os
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree

import psycopg2
import requests
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError


DEFAULT_DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5433")),
    "dbname": os.getenv("DB_NAME", "academic"),
    "user": os.getenv("DB_USER", "academic"),
    "password": os.getenv("DB_PASSWORD", "academic"),
}
DEFAULT_GROBID_URL = os.getenv("GROBID_URL", "http://localhost:8070")


def extract_text_from_pdf(pdf_path: Path, max_pages: int = 2) -> str:
    try:
        reader = PdfReader(str(pdf_path))
    except PdfReadError:
        return ""
    text_chunks = []
    for page in reader.pages[:max_pages]:
        page_text = page.extract_text() or ""
        if page_text:
            text_chunks.append(page_text)
    return "\n".join(text_chunks)


def grobid_is_available(base_url: str) -> bool:
    try:
        response = requests.get(f"{base_url}/api/isalive", timeout=2)
        return response.ok
    except requests.RequestException:
        return False


def normalize_whitespace(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return " ".join(value.split()).strip() or None


def element_text(element: Optional[ElementTree.Element]) -> Optional[str]:
    if element is None:
        return None
    return normalize_whitespace(" ".join(element.itertext()))


def parse_grobid_author(author_el: ElementTree.Element, ns: Dict[str, str]) -> Optional[str]:
    surname = author_el.findtext(".//tei:surname", namespaces=ns) or ""
    forenames = author_el.findall(".//tei:forename", namespaces=ns)
    forename = " ".join([el.text for el in forenames if el.text]) if forenames else ""
    full_name = " ".join(part for part in [forename, surname] if part).strip()
    return full_name or None


def parse_publication_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    value = value.strip()
    match = re.search(r"\b(19|20)\d{2}-\d{2}-\d{2}\b", value)
    if match:
        return date.fromisoformat(match.group(0))
    match = re.search(r"\b(19|20)\d{2}-\d{2}\b", value)
    if match:
        year, month = match.group(0).split("-")
        return date(int(year), int(month), 1)
    match = re.search(r"\b(19|20)\d{2}\b", value)
    if match:
        return date(int(match.group(0)), 1, 1)
    return None


def extract_document_type(root: ElementTree.Element, ns: Dict[str, str]) -> Optional[str]:
    bibl_struct = root.find(".//tei:biblStruct", namespaces=ns)
    if bibl_struct is not None:
        bibl_type = bibl_struct.attrib.get("type")
        if bibl_type:
            return normalize_whitespace(bibl_type)

    for class_code in root.findall(".//tei:textClass//tei:classCode", namespaces=ns):
        if class_code.text:
            return normalize_whitespace(class_code.text)

    for term in root.findall(".//tei:textClass//tei:keywords//tei:term", namespaces=ns):
        if term.text and len(term.text.split()) <= 4:
            candidate = term.text.strip().lower()
            if candidate in {"article", "review", "book", "chapter", "conference", "preprint"}:
                return candidate
    return None


def extract_affiliations(author_el: ElementTree.Element, ns: Dict[str, str]) -> List[str]:
    affiliations = []
    for aff in author_el.findall(".//tei:affiliation", namespaces=ns):
        parts = []
        for org in aff.findall(".//tei:orgName", namespaces=ns):
            org_text = element_text(org)
            if org_text:
                parts.append(org_text)
        address = aff.find(".//tei:address", namespaces=ns)
        address_text = element_text(address)
        if address_text:
            parts.append(address_text)
        if parts:
            affiliations.append(normalize_whitespace(", ".join(parts)))
    return [aff for aff in affiliations if aff]


def extract_countries(author_el: ElementTree.Element, ns: Dict[str, str]) -> List[str]:
    countries = []
    for country_el in author_el.findall(".//tei:affiliation//tei:address//tei:country", namespaces=ns):
        country = normalize_whitespace(country_el.text)
        if country:
            countries.append(country)
    return countries


def extract_metadata_grobid(pdf_path: Path, base_url: str) -> Optional[Dict]:
    try:
        with pdf_path.open("rb") as handle:
            response = requests.post(
                f"{base_url}/api/processHeaderDocument",
                files={"input": handle},
                data={"consolidateHeader": "1"},
                headers={"Accept": "application/xml"},
                timeout=30,
            )
        response.raise_for_status()
    except requests.RequestException:
        return None

    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError:
        return None

    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    title = root.findtext(".//tei:titleStmt/tei:title", namespaces=ns)
    document_type = extract_document_type(root, ns)

    authors = []
    affiliations = []
    countries = []
    for author_el in root.findall(".//tei:sourceDesc//tei:author", namespaces=ns):
        author_name = parse_grobid_author(author_el, ns)
        if author_name:
            authors.append(author_name)
        affiliations.extend(extract_affiliations(author_el, ns))
        countries.extend(extract_countries(author_el, ns))

    if not authors:
        for author_el in root.findall(".//tei:titleStmt//tei:author", namespaces=ns):
            author_name = parse_grobid_author(author_el, ns)
            if author_name:
                authors.append(author_name)
            affiliations.extend(extract_affiliations(author_el, ns))
            countries.extend(extract_countries(author_el, ns))

    keywords = [
        term.text.strip()
        for term in root.findall(".//tei:keywords//tei:term", namespaces=ns)
        if term.text and term.text.strip()
    ]

    year = None
    publication_date = None
    for date_el in root.findall(".//tei:publicationStmt//tei:date", namespaces=ns):
        publication_date = parse_publication_date(date_el.attrib.get("when") or date_el.text)
        if publication_date:
            year = publication_date.year
            break
        if date_el.text:
            year = extract_year(date_el.text)
            if year:
                break
        when_attr = date_el.attrib.get("when")
        if when_attr:
            year = extract_year(when_attr)
            if year:
                break

    if not publication_date:
        for date_el in root.findall(".//tei:imprint//tei:date", namespaces=ns):
            publication_date = parse_publication_date(date_el.attrib.get("when") or date_el.text)
            if publication_date:
                year = publication_date.year
                break

    journal_title = root.findtext(".//tei:monogr/tei:title[@level='j']", namespaces=ns)
    book_title = root.findtext(".//tei:monogr/tei:title[@level='m']", namespaces=ns)
    if not journal_title and not book_title:
        book_title = root.findtext(".//tei:monogr/tei:title", namespaces=ns)

    publisher = root.findtext(".//tei:publicationStmt/tei:publisher", namespaces=ns)
    if not publisher:
        publisher = root.findtext(".//tei:monogr/tei:imprint/tei:publisher", namespaces=ns)

    abstract = element_text(root.find(".//tei:profileDesc/tei:abstract", namespaces=ns))

    return {
        "title": title,
        "document_type": document_type,
        "publication_date": publication_date,
        "journal_title": journal_title,
        "book_title": book_title,
        "publisher": publisher,
        "authors": authors or None,
        "affiliations": sorted(set(affiliations)) or None,
        "countries": sorted(set(countries)) or None,
        "abstract": abstract,
        "year": year,
        "keywords": keywords or None,
    }


def extract_year(text: str) -> Optional[int]:
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if match:
        return int(match.group(0))
    return None


def split_authors(authors_line: str) -> List[str]:
    normalized = authors_line.replace(" and ", ",").replace(";", ",")
    parts = [part.strip() for part in normalized.split(",")]
    return [part for part in parts if part]


def split_keywords(keywords_line: str) -> List[str]:
    normalized = keywords_line.replace(";", ",")
    parts = [part.strip() for part in normalized.split(",")]
    return [part for part in parts if part]


def extract_keywords(text: str) -> List[str]:
    match = re.search(
        r"(?:Keywords?|Index Terms?)\s*[:\-]\s*(.+)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    line = match.group(1).splitlines()[0]
    return split_keywords(line)


def extract_authors(lines: List[str]) -> List[str]:
    for line in lines[:5]:
        match = re.search(r"Authors?\s*[:\-]\s*(.+)", line, flags=re.IGNORECASE)
        if match:
            return split_authors(match.group(1))
    if len(lines) > 1 and len(lines[1]) <= 120:
        return split_authors(lines[1])
    return []


def extract_title(lines: List[str]) -> Optional[str]:
    if not lines:
        return None
    return lines[0]


def extract_abstract(text: str) -> Optional[str]:
    match = re.search(
        r"\bAbstract\b\s*[:\-]?\s*(.+?)(?:\n\s*\n|\bIntroduction\b|\bKeywords\b)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return normalize_whitespace(match.group(1))


def extract_metadata(text: str) -> Dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = extract_title(lines)
    authors = extract_authors(lines)
    year = extract_year(text)
    keywords = extract_keywords(text)
    abstract = extract_abstract(text)
    raw_text_snippet = text[:500].strip() if text else None
    return {
        "title": title,
        "document_type": None,
        "publication_date": None,
        "journal_title": None,
        "book_title": None,
        "publisher": None,
        "authors": authors or None,
        "affiliations": None,
        "countries": None,
        "abstract": abstract,
        "year": year,
        "keywords": keywords or None,
        "raw_text_snippet": raw_text_snippet,
    }


def iter_pdfs(directory: Path, recursive: bool) -> List[Path]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return list(directory.glob(pattern))


def upsert_paper(conn, file_path: Path, metadata: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO papers (
                file_path,
                title,
                document_type,
                publication_date,
                journal_title,
                book_title,
                publisher,
                authors,
                affiliations,
                countries,
                abstract,
                year,
                keywords,
                raw_text_snippet,
                processed_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (file_path) DO UPDATE SET
                title = EXCLUDED.title,
                document_type = EXCLUDED.document_type,
                publication_date = EXCLUDED.publication_date,
                journal_title = EXCLUDED.journal_title,
                book_title = EXCLUDED.book_title,
                publisher = EXCLUDED.publisher,
                authors = EXCLUDED.authors,
                affiliations = EXCLUDED.affiliations,
                countries = EXCLUDED.countries,
                abstract = EXCLUDED.abstract,
                year = EXCLUDED.year,
                keywords = EXCLUDED.keywords,
                raw_text_snippet = EXCLUDED.raw_text_snippet,
                processed_at = NOW(),
                updated_at = NOW();
            """,
            (
                str(file_path),
                metadata["title"],
                metadata["document_type"],
                metadata["publication_date"],
                metadata["journal_title"],
                metadata["book_title"],
                metadata["publisher"],
                metadata["authors"],
                metadata["affiliations"],
                metadata["countries"],
                metadata["abstract"],
                metadata["year"],
                metadata["keywords"],
                metadata["raw_text_snippet"],
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest academic paper metadata into Postgres.")
    parser.add_argument("directory", help="Directory containing PDF papers.")
    parser.add_argument("--recursive", action="store_true", help="Scan subdirectories.")
    parser.add_argument("--dry-run", action="store_true", help="Parse files without writing to DB.")
    parser.add_argument("--no-grobid", action="store_true", help="Skip GROBID metadata extraction.")
    parser.add_argument("--grobid-url", default=DEFAULT_GROBID_URL, help="Base URL for GROBID.")
    args = parser.parse_args()

    directory = Path(args.directory).expanduser().resolve()
    if not directory.exists() or not directory.is_dir():
        raise SystemExit(f"Directory not found: {directory}")

    pdf_files = iter_pdfs(directory, args.recursive)
    if not pdf_files:
        print("No PDF files found.")
        return

    conn = None
    if not args.dry_run:
        conn = psycopg2.connect(**DEFAULT_DB_CONFIG)

    use_grobid = False
    if not args.no_grobid and grobid_is_available(args.grobid_url):
        use_grobid = True

    processed = 0
    for pdf_path in pdf_files:
        text = extract_text_from_pdf(pdf_path)
        metadata = None
        if use_grobid:
            metadata = extract_metadata_grobid(pdf_path, args.grobid_url)
        if not metadata:
            metadata = extract_metadata(text)
        metadata["raw_text_snippet"] = text[:500].strip() if text else None
        processed += 1

        if args.dry_run:
            print(f"[DRY RUN] {pdf_path.name} -> {metadata}")
            continue

        upsert_paper(conn, pdf_path, metadata)

    if conn:
        conn.commit()
        conn.close()

    print(f"Processed {processed} papers.")


if __name__ == "__main__":
    main()
