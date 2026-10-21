__lazy_modules__ = {
    "streamlit",
    "pinionai.file_type_detection",
}

import csv
import io
import mimetypes
from urllib.parse import urlsplit

import streamlit as st

from pinionai.file_type_detection import decode_data_url, is_text_file_type

_DOWNLOADABLE_FILE_NAMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "Download XLSX",
        "response.xlsx",
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "Download PPTX",
        "response.pptx",
    ),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "Download DOCX",
        "response.docx",
    ),
    "text/csv": ("Download CSV", "response.csv"),
}


def render_response(content: str, file_type: str = "text/plain") -> None:
    """Render a text response or expose a detected file response in Streamlit."""
    file_type = file_type or "text/plain"
    parsed_url = urlsplit(content)
    if parsed_url.scheme in {"http", "https"}:
        if file_type in _DOWNLOADABLE_FILE_NAMES:
            label, _ = _DOWNLOADABLE_FILE_NAMES[file_type]
            st.link_button(label, content)
        elif file_type == "application/pdf":
            st.pdf(content, height=700, alt="PDF response")
            st.link_button("Download PDF", content)
        elif file_type.startswith("image/"):
            st.image(content)
        elif file_type.startswith("audio/"):
            st.audio(content, format=file_type)
        elif file_type.startswith("video/"):
            st.video(content)
        else:
            st.link_button("Open file", content)
        return

    payload = decode_data_url(content)
    if payload is None:
        payload = content.encode("utf-8")

    if file_type == "text/csv":
        label, file_name = _DOWNLOADABLE_FILE_NAMES[file_type]
        csv_text = payload.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        if rows:
            st.dataframe(rows)
        else:
            st.text(csv_text)
        st.download_button(
            label,
            data=payload,
            file_name=file_name,
            mime=file_type,
        )
        return

    if is_text_file_type(file_type):
        if file_type == "text/markdown":
            st.markdown(content)
        elif file_type == "application/json":
            st.code(content, language="json")
        else:
            st.text(content)
        return

    if file_type == "application/pdf":
        st.pdf(payload, height=700, alt="PDF response")
        st.download_button(
            "Download PDF",
            data=payload,
            file_name="response.pdf",
            mime=file_type,
        )
    elif file_type.startswith("image/"):
        st.image(payload)
    elif file_type.startswith("audio/"):
        st.audio(payload, format=file_type)
    elif file_type.startswith("video/"):
        st.video(payload)
    elif file_type in _DOWNLOADABLE_FILE_NAMES:
        label, file_name = _DOWNLOADABLE_FILE_NAMES[file_type]
        st.download_button(
            label,
            data=payload,
            file_name=file_name,
            mime=file_type,
        )
    else:
        extension = mimetypes.guess_extension(file_type) or ".bin"
        st.download_button(
            "Download file",
            data=payload,
            file_name=f"response{extension}",
            mime=file_type,
        )
