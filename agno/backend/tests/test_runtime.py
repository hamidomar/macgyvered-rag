from types import SimpleNamespace

from src.runtime import TurboRefiSessionService
from src.state import merge_session_state


class FakeAgent:
    def __init__(self):
        self.sessions = {}

    def get_session_state(self, session_id):
        return self.sessions.get(session_id)

    def update_session_state(self, session_id=None, session_state_updates=None):
        current = self.sessions.get(session_id, {}).copy()
        current.update(session_state_updates or {})
        self.sessions[session_id] = current

    def run(self, message, session_id=None, session_state=None):
        self.sessions[session_id] = merge_session_state(self.sessions.get(session_id, {}), session_state or {})
        return SimpleNamespace(content=f"processed: {message}")


def test_create_session_persists_state():
    service = TurboRefiSessionService(agent=FakeAgent())

    session_id, response, state = service.create_session_from_mortgage_data(
        {"loan_balance": 250000},
        session_id="session-123",
    )

    assert session_id == "session-123"
    assert "processed" in response
    assert service.session_exists(session_id) is True
    assert state["mortgage_data"] == {"loan_balance": 250000}
    assert service.get_state(session_id)["documents_received"] == [
        "mortgage_statement"
    ]


def test_upload_secondary_document_blocks_until_paystubs_and_w2_are_complete():
    service = TurboRefiSessionService(agent=FakeAgent())
    service.create_session_from_mortgage_data(
        {"loan_balance": 250000},
        session_id="session-123",
    )

    response, state = service.upload_secondary_document(
        "session-123",
        "w2",
        {"wages_box1": 120000, "tax_year": 2025},
    )

    assert "cannot proceed to eligibility yet" in response.lower()
    assert state["current_phase"] == "awaiting_docs"
    assert state["documents_pending"] == ["paystub", "paystub"]


def test_finalize_run_rejects_packet_without_required_tooling():
    service = TurboRefiSessionService(agent=FakeAgent())
    service.create_session_from_mortgage_data(
        {"loan_balance": 250000, "borrower_name": "Sarah Chen"},
        session_id="session-123",
    )

    response, state = service._finalize_run(
        "session-123",
        """{
            "borrower_name": "Microsoft Employee",
            "use_case": "uc1_rate_term_refi",
            "fnma_eligible": true,
            "fhlmc_eligible": true
        }""",
    )

    assert "draft packet is invalid" in response.lower()
    assert state["current_phase"] == "assessment"
    assert service.get_state("session-123").get("loan_recommendation_packet") is None
