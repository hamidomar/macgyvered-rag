from fastapi.testclient import TestClient

from src.app import api


client = TestClient(api)


def test_ingest_creates_session(monkeypatch):
    extracted = {"loan_balance": 250000}

    monkeypatch.setattr("src.app.extract_document", lambda *_args, **_kwargs: extracted)
    monkeypatch.setattr(
        "src.app.service.create_session_from_mortgage_data",
        lambda payload: ("session-123", "Thanks, I reviewed the mortgage statement.", {"current_phase": "greeting"}),
    )

    response = client.post(
        "/ingest",
        files={"file": ("statement.pdf", b"dummy-pdf", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "session-123",
        "response": "Thanks, I reviewed the mortgage statement.",
        "current_phase": "greeting",
        "document_type": "mortgage_statement",
        "tool_trace": [],
    }


def test_ingest_infers_supporting_doc_type(monkeypatch):
    extracted = {"wages_box1": 120000, "tax_year": 2025}

    monkeypatch.setattr("src.app.service.session_exists", lambda session_id: session_id == "session-123")
    monkeypatch.setattr("src.app.infer_supporting_doc_type", lambda *_args, **_kwargs: "w2")
    monkeypatch.setattr("src.app.extract_document", lambda *_args, **_kwargs: extracted)

    recorded = {}

    def fake_upload(session_id, doc_type, payload):
        recorded["session_id"] = session_id
        recorded["doc_type"] = doc_type
        recorded["payload"] = payload
        return "I reviewed the W-2. Do you have a paystub as well?", {"current_phase": "assessment"}

    monkeypatch.setattr("src.app.service.upload_secondary_document", fake_upload)

    response = client.post(
        "/ingest",
        data={"session_id": "session-123"},
        files={"file": ("w2.pdf", b"dummy-pdf", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "session-123",
        "response": "I reviewed the W-2. Do you have a paystub as well?",
        "current_phase": "assessment",
        "document_type": "w2",
        "tool_trace": [],
    }
    assert recorded == {
        "session_id": "session-123",
        "doc_type": "w2",
        "payload": extracted,
    }


def test_ingest_rejects_non_mortgage_first_upload():
    response = client.post(
        "/ingest",
        data={"doc_type": "w2"},
        files={"file": ("w2.pdf", b"dummy-pdf", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The first upload must be a mortgage statement"
