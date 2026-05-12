"""
Stage 2 — Extraction
---------------------
Converts raw documents (PDF, scanned PDF, HTML) into structured legal text.

Priority:
  1. Docling     — digital PDFs (best structure preservation)
  2. Surya OCR   — scanned PDFs (multilingual)
  3. Tesseract   — scanned PDFs fallback
  4. Playwright + BeautifulSoup — HTML pages

Output per document:
  {
    "url": str,
    "title": str,
    "tier": int,
    "language": str,
    "doc_type": str,
    "effective_date": str,
    "sha256": str,
    "articles": [
      { "id": str, "section": str, "text": str }
    ]
  }
"""

from __future__ import annotations
import hashlib
import logging
import os
import re
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_document(source) -> dict:
    """
    Route a DiscoveredSource to the correct extractor.
    Returns structured document dict ready for authority.py
    """
    doc_type = getattr(source, "doc_type", "html")

    if doc_type in ("pdf", "scanned_pdf"):
        raw_text, method = _extract_pdf(source.url)
    else:
        raw_text, method = _extract_html(source.url)

    if not raw_text:
        country_fallback = _demo_fallback_for_country(_infer_demo_country(source))
        if country_fallback:
            raw_text, method = country_fallback, "bundled_demo_text"

    logger.info(f"[extract] '{source.title}' via {method} — {len(raw_text)} chars")

    articles = _parse_articles(raw_text, source.language)

    return {
        "url": source.url,
        "title": source.title,
        "tier": source.tier,
        "language": source.language,
        "doc_type": doc_type,
        "extraction_method": method,
        "effective_date": "",          # filled by authority.py if detected
        "sha256": hashlib.sha256(raw_text.encode()).hexdigest(),
        "articles": articles,
    }


def _extract_pdf(url: str) -> tuple[str, str]:
    """Try Docling first, fall back to Surya OCR, then Tesseract."""
    fallback = _demo_fallback_text(url)
    try:
        tmp_path, should_cleanup = _resolve_pdf_input(url)
    except Exception as e:
        if fallback:
            logger.warning(f"[extract] Download failed for {url}: {e} — using bundled demo text")
            return fallback, "bundled_demo_text"
        logger.warning(f"[extract] Download failed for {url}: {e}")
        return "", "failed"

    # Try Docling (best for digital PDFs)
    try:
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result    = converter.convert(tmp_path)
        text      = result.document.export_to_markdown()
        if text and len(text) > 200:
            _cleanup_temp_file(tmp_path, should_cleanup)
            return text, "docling"
    except Exception as e:
        logger.warning(f"[extract] Docling failed: {e} — trying Surya OCR")

    # Try Surya OCR (best for scanned multilingual PDFs)
    try:
        from surya.ocr import run_ocr
        from surya.model.detection.model import load_model as load_det_model
        from surya.model.recognition.model import load_model as load_rec_model
        from surya.model.recognition.processor import load_processor
        from pdf2image import convert_from_path
        from PIL import Image

        images  = convert_from_path(tmp_path)
        det_model, det_processor = load_det_model(), None
        rec_model, rec_processor = load_rec_model(), load_processor()
        predictions = run_ocr(images, [["en"]] * len(images), det_model, det_processor, rec_model, rec_processor)
        text = "\n".join(
            line.text for page in predictions for line in page.text_lines
        )
        if text and len(text) > 100:
            _cleanup_temp_file(tmp_path, should_cleanup)
            return text, "surya_ocr"
    except Exception as e:
        logger.warning(f"[extract] Surya OCR failed: {e} — trying Tesseract")

    # Tesseract fallback
    try:
        import pytesseract
        from pdf2image import convert_from_path
        images = convert_from_path(tmp_path)
        text   = "\n".join(pytesseract.image_to_string(img) for img in images)
        _cleanup_temp_file(tmp_path, should_cleanup)
        return text, "tesseract"
    except Exception as e:
        logger.error(f"[extract] Tesseract failed: {e}")

    _cleanup_temp_file(tmp_path, should_cleanup)
    if fallback:
        return fallback, "bundled_demo_text"
    return "", "failed"


def _extract_html(url: str) -> tuple[str, str]:
    """Extract text from HTML page using requests + BeautifulSoup."""
    fallback = _demo_fallback_text(url)
    if _is_file_url(url):
        try:
            path = _path_from_file_url(url)
            text = path.read_text(encoding="utf-8")
            return text, "local_file"
        except Exception as e:
            logger.warning(f"[extract] Local HTML extraction failed for {url}: {e}")
            return "", "failed"

    try:
        import requests
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "RDTII-Agent/0.1 (UN Hackathon Research Tool)"}
        resp    = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # Remove nav, footer, scripts
        for tag in soup(["nav", "footer", "script", "style", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        if len(text.strip()) < 200 and fallback:
            return fallback, "bundled_demo_text"
        return text, "beautifulsoup"
    except Exception as e:
        if fallback:
            logger.warning(f"[extract] HTML extraction failed for {url}: {e} — using bundled demo text")
            return fallback, "bundled_demo_text"
        logger.warning(f"[extract] HTML extraction failed for {url}: {e}")
        return "", "failed"


def _resolve_pdf_input(url: str) -> tuple[str, bool]:
    """Return a local PDF path and whether it should be deleted after use."""
    if _is_file_url(url):
        path = _path_from_file_url(url)
        if not path.exists():
            raise FileNotFoundError(path)
        if not path.is_file():
            raise ValueError(f"Not a file: {path}")
        return str(path), False

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        urllib.request.urlretrieve(url, tmp.name)
        return tmp.name, True


def _is_file_url(url: str) -> bool:
    """Return True for local file URLs."""
    return urllib.parse.urlparse(url).scheme == "file"


def _path_from_file_url(url: str) -> Path:
    """Convert a file:// URL into a filesystem path."""
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc not in {"", "localhost"}:
        raise ValueError(f"Only local file URLs are supported: {url}")
    return Path(urllib.request.url2pathname(parsed.path)).expanduser()


def _cleanup_temp_file(path: str, should_cleanup: bool) -> None:
    """Delete temp files created for downloaded PDFs."""
    if not should_cleanup:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _parse_articles(text: str, language: str = "en") -> list[dict]:
    """
    Split raw legal text into article/section chunks.
    Looks for patterns like 'Section 28', 'Article 26', 'มาตรา 28' (Thai).
    Returns list of {id, section, text} dicts.
    """
    if not text:
        return []

    # Patterns: English, Vietnamese (Điều), Thai (มาตรา), Russian (Статья).
    # Keep these non-capturing; captured alternations create None fragments in
    # re.split and make section IDs unreliable.
    combined_pattern = (
        r"^[ \t]*(?:Section\s+\d+[\w.]*)|"
        r"^[ \t]*(?:Article\s+\d+[\w.]*)|"
        r"^[ \t]*(?:Điều\s+\d+)|"
        r"^[ \t]*(?:มาตรา\s+\d+)|"
        r"^[ \t]*(?:Статья\s+\d+)|"
        r"^[ \t]*(?:Art\.\s*\d+[\w.]*)"
    )

    matches = list(re.finditer(combined_pattern, text, flags=re.IGNORECASE | re.MULTILINE))
    if not matches:
        cleaned = text.strip()
        return [{"id": "document", "section": "Document", "text": cleaned}] if cleaned else []

    splits = []
    preamble = text[:matches[0].start()].strip()
    if len(preamble) >= 30:
        splits.append(("Document title", preamble))
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        splits.append((match.group(0).strip(), text[match.start():end]))

    articles = []

    for i, (section_id, chunk) in enumerate(splits):
        if not chunk:
            continue
        chunk = chunk.strip()
        if len(chunk) < 30:    # skip tiny fragments
            continue

        articles.append({
            "id": _slugify(section_id),
            "section": section_id,
            "text": chunk,
        })

    logger.info(f"[extract] Parsed {len(articles)} article chunks")
    return articles


def _slugify(text: str) -> str:
    """Convert 'Section 28' → 's28' for use as an ID."""
    return re.sub(r"[^a-z0-9]", "", text.lower().replace(" ", ""))


def _demo_fallback_text(url: str) -> str:
    """
    Small bundled excerpt set for the Thailand, Vietnam, and Singapore demos.

    The project specification requires a runnable end-to-end demo. These excerpts
    keep the pipeline auditable when network access or heavyweight PDF/OCR
    dependencies are unavailable in a hackathon environment.
    """
    url_lower = url.lower()

    if "personal-data-protection-act-be-2562-2019.pdf" in url_lower:
        return """
Personal Data Protection Act B.E. 2562 (2019)

Section 1. This Act is called the "Personal Data Protection Act B.E. 2562".

Section 28. In the event that the data controller sends or transfers the personal data to a foreign country, the destination country or international organization that receives such personal data shall have adequate data protection standard, and shall be carried out in accordance with the rules for the protection of personal data as prescribed by the Committee.

Section 29. In the absence of the adequacy decision under Section 28, the data controller may send or transfer the personal data to a foreign country where the data subject has given consent after having been informed of the inadequate personal data protection standards of the destination country or international organization.

Section 37. The data controller shall have the following duties: provide appropriate security measures for preventing the unauthorized or unlawful loss, access to, use, alteration, correction or disclosure of personal data.

Section 39. The data controller shall maintain records of personal data processing activities in order to enable the data subject and the Office to check upon.

Section 41. The data controller and the data processor shall designate a data protection officer in the case where the activities of the data controller or the data processor require regular monitoring of personal data or the system by reason of having a large number of personal data as prescribed by the Committee.

Section 80. The competent official shall have the power to enter the premises of the data controller or data processor during working hours for the purpose of inspection and shall have the power to seize or attach documents, evidence or any other things related to the commission of an offense under this Act.
"""

    if (
        "vanban.chinhphu" in url_lower
        or "cybersecurity" in url_lower
        or "decree-13" in url_lower
    ):
        return _demo_fallback_for_country("vietnam")

    if (
        "agc.gov.sg" in url_lower
        or "pdpa2012" in url_lower
        or "pdpc.gov.sg" in url_lower
    ):
        return _demo_fallback_for_country("singapore")

    return ""


def _demo_fallback_for_country(country: str) -> str:
    """Return bundled demo legal text for a supported country."""
    country_key = (country or "").lower().strip()

    if country_key == "thailand":
        return """
Personal Data Protection Act B.E. 2562 (2019)

Section 1. This Act is called the "Personal Data Protection Act B.E. 2562".

Section 28. In the event that the data controller sends or transfers the personal data to a foreign country, the destination country or international organization that receives such personal data shall have adequate data protection standard, and shall be carried out in accordance with the rules for the protection of personal data as prescribed by the Committee.

Section 29. In the absence of the adequacy decision under Section 28, the data controller may send or transfer the personal data to a foreign country where the data subject has given consent after having been informed of the inadequate personal data protection standards of the destination country or international organization.

Section 37. The data controller shall have the following duties: provide appropriate security measures for preventing the unauthorized or unlawful loss, access to, use, alteration, correction or disclosure of personal data.

Section 39. The data controller shall maintain records of personal data processing activities in order to enable the data subject and the Office to check upon.

Section 41. The data controller and the data processor shall designate a data protection officer in the case where the activities of the data controller or the data processor require regular monitoring of personal data or the system by reason of having a large number of personal data as prescribed by the Committee.

Section 80. The competent official shall have the power to enter the premises of the data controller or data processor during working hours for the purpose of inspection and shall have the power to seize or attach documents, evidence or any other things related to the commission of an offense under this Act.
"""

    if country_key == "vietnam":
        return """
Vietnam Cybersecurity Law (Law 24/2018/QH14)

Article 26. Domestic storage of data: Domestic enterprises providing services on telecommunications networks and the internet and other value-added services in cyberspace in Vietnam that collect, exploit, analyze and process data about personal information, data about relationships of their service users, and data generated by service users in Vietnam shall store such data in Vietnam for a prescribed period of time. Foreign enterprises that provide services on telecommunications networks and the internet and other value-added services in cyberspace in Vietnam shall store data in Vietnam for a period of time as prescribed by the Government and set up branches or representative offices in Vietnam.

Vietnam Decree 13/2023/ND-CP on Personal Data Protection

Article 9. Personal data shall be processed only for the purpose for which it was collected. The processing of personal data for another purpose requires the consent of the data subject.

Article 25. The transfer of personal data of Vietnamese citizens to overseas must be consented to by the data subject and meet the conditions prescribed in this Decree. The transferring party must assess the impact of transferring personal data overseas before conducting the transfer.
"""

    if country_key == "singapore":
        return """
Personal Data Protection Act 2012

Section 26. An organisation must not transfer personal data to a country or territory outside Singapore except in accordance with requirements prescribed under this Act to ensure that organisations provide a standard of protection to personal data so transferred that is comparable to the protection under this Act.

Section 24. An organisation must protect personal data in its possession or under its control by making reasonable security arrangements to prevent unauthorised access, collection, use, disclosure, copying, modification, disposal or similar risks.

Section 11. Despite any contractual agreement, an organisation remains responsible for personal data in its possession or under its control, even after the data has been transferred to a data processor.
"""

    return ""


def _infer_demo_country(source) -> str:
    """Infer the demo country from source metadata when URL fallback misses."""
    combined = f"{getattr(source, 'url', '')} {getattr(source, 'title', '')}".lower()
    if any(token in combined for token in ("thailand", "oag.go.th", "ratchakitcha", "etda.or.th")):
        return "thailand"
    if any(token in combined for token in ("vietnam", "vanban.chinhphu", "decree 13", "decree-13", "cybersecurity")):
        return "vietnam"
    if any(token in combined for token in ("singapore", "agc.gov.sg", "pdpa2012", "pdpc.gov.sg")):
        return "singapore"
    return ""
