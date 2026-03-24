import pytest
from unittest.mock import patch, MagicMock
from src.tools.extraction import extract_document

@patch("src.tools.extraction.PdfReader")
@patch("src.tools.extraction.client.chat.completions.create")
def test_extract_mortgage_statement(mock_create, mock_pdfreader):
    mock_pdfreader.return_value = MagicMock()

    mock_response = """```json
    {
        "current_rate_percent": 5.5,
        "loan_balance": 250000,
        "servicer_name": "Test Servicer",
        "loan_number": "123456789",
        "gse_owner": "fnma",
        "monthly_pi": 1500,
        "monthly_pmi": 100,
        "original_property_value": 300000
    }
    ```"""
    
    class MockMessage:
        content = mock_response

    class MockChoice:
        message = MockMessage()

    class MockCompletion:
        choices = [MockChoice()]

    mock_create.return_value = MockCompletion()

    result = extract_document(b"dummy pdf bytes", "mortgage_statement")
    assert isinstance(result, dict)
    assert result["gse_owner"] == "fnma"
    assert result["loan_balance"] == 250000
