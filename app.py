"""
Streamlit UI for the RDTII Regulatory Intelligence Agent.

The UI is intentionally thin: it runs the existing backend pipeline and reads
the JSON-LD/review outputs. It does not implement separate scoring logic.
"""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path

import streamlit as st

from main import run_pipeline
import pipeline.reason as reason_module


COUNTRIES = ["thailand", "vietnam", "singapore"]
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./outputs"))


def main() -> None:
    st.set_page_config(page_title="RDTII Agent", layout="wide")

    st.title("RDTII Regulatory Intelligence Agent")

    controls, results = st.columns([0.28, 0.72], gap="large")
    with controls:
        country = st.selectbox("Country", COUNTRIES, format_func=str.title)
        pillars = st.multiselect("Pillars", [6, 7], default=[6, 7])
        model = st.text_input("Ollama model", value="llama3.1:8b")
        base_url = st.text_input("Ollama base URL", value=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))

        run_clicked = st.button("Run analysis", type="primary", use_container_width=True)
        st.divider()
        st.caption("Outputs are loaded from the current output directory.")
        st.code(str(OUTPUT_DIR), language=None)

    if run_clicked:
        if not pillars:
            st.warning("Select at least one pillar.")
        else:
            _run_analysis(country, pillars, model, base_url)

    with results:
        dataset = _load_dataset(country)
        if dataset:
            _render_results(country, dataset)
        else:
            st.info("Run an analysis or generate CLI outputs to view scores here.")


def _run_analysis(country: str, pillars: list[int], model: str, base_url: str) -> None:
    os.environ["OLLAMA_MODEL"] = model
    os.environ["OLLAMA_BASE_URL"] = base_url
    reason_module._OLLAMA_UNAVAILABLE = False

    log_buffer = io.StringIO()
    with st.status(f"Running {country.title()} analysis...", expanded=True) as status:
        with redirect_stdout(log_buffer):
            scores = run_pipeline(country, pillars)
        status.update(label=f"Completed {country.title()} analysis", state="complete")

    confirmed = sum(1 for score in scores if not score.human_review_required)
    st.success(f"Completed with {confirmed} confirmed scores and {len(scores) - confirmed} review items.")
    with st.expander("Run log"):
        st.code(log_buffer.getvalue(), language=None)


def _load_dataset(country: str) -> dict | None:
    path = OUTPUT_DIR / f"{country}_rdtii_dataset.jsonld"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        st.error(f"Could not parse {path}: {exc}")
        return None


def _render_results(country: str, dataset: dict) -> None:
    indicators = dataset.get("rdtii:indicators", [])
    confirmed = [item for item in indicators if not item.get("human_review_required")]
    review = [item for item in indicators if item.get("human_review_required")]

    summary_cols = st.columns(4)
    summary_cols[0].metric("Indicators", len(indicators))
    summary_cols[1].metric("Confirmed", len(confirmed))
    summary_cols[2].metric("Human Review", len(review))
    summary_cols[3].metric("Run", dataset.get("rdtii:runId", "")[-6:])

    rows = [
        {
            "ID": item.get("rdtii:indicatorId"),
            "Indicator": item.get("rdtii:indicatorName"),
            "Score": item.get("score"),
            "Confidence": item.get("confidence"),
            "Tier": item.get("rdtii:sourceTier"),
            "Method": item.get("extraction_method"),
            "Review": item.get("human_review_required"),
        }
        for item in indicators
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)

    tab_scores, tab_review, tab_downloads = st.tabs(["Evidence", "Review Queue", "Downloads"])
    with tab_scores:
        for item in confirmed:
            st.subheader(f"{item.get('rdtii:indicatorId')} - {item.get('rdtii:indicatorName')}")
            st.write(
                {
                    "score": item.get("score"),
                    "confidence": item.get("confidence"),
                    "article": item.get("article_ref"),
                    "source": item.get("rdtii:sourceTitle"),
                    "extraction_method": item.get("extraction_method"),
                }
            )
            st.markdown(f"> {item.get('verbatim_quote', '')}")

    with tab_review:
        if not review:
            st.success("No indicators require human review.")
        for item in review:
            st.subheader(f"{item.get('rdtii:indicatorId')} - {item.get('rdtii:indicatorName')}")
            st.write(item.get("rdtii:humanReviewReason") or "Review required.")
            st.caption(f"{item.get('rdtii:sourceTitle')} | {item.get('article_ref')}")

    with tab_downloads:
        _download_file("JSON-LD dataset", OUTPUT_DIR / f"{country}_rdtii_dataset.jsonld")
        _download_file("Country brief", OUTPUT_DIR / f"{country}_country_brief.md")
        _download_file("Review queue", OUTPUT_DIR / f"{country}_review_queue.json")


def _download_file(label: str, path: Path) -> None:
    if not path.exists():
        st.caption(f"{label}: not generated")
        return
    st.download_button(
        label,
        data=path.read_bytes(),
        file_name=path.name,
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
