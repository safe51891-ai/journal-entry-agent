from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID_DOC = (
    "Invoice: INV-9001\nDate: 2026-10-03\nVendor: Northwind Cloud\nCategory: software\n"
    "Total: 480.00\nStatus: unpaid\nDescription: Monthly hosting"
)
MAPPING_GAP_DOC = (
    "Invoice: INV-9002\nDate: 2026-10-16\nVendor: Brightline Ads\nCategory: marketing\n"
    "Total: 750.00\nStatus: unpaid\nDescription: Campaign"
)


def test_index_serves_frontend():
    response = client.get("/")
    assert response.status_code == 200
    assert "Journal Entry Agent" in response.text


def test_samples_endpoint_returns_synthetic_data():
    response = client.get("/api/samples")
    assert response.status_code == 200
    assert len(response.json()) == 11


def test_valid_document_is_pending_then_approved():
    created = client.post("/api/propose", json={"document": VALID_DOC})
    assert created.status_code == 201
    entry = created.json()
    assert entry["status"] == "pending"
    assert entry["issues"] == []

    approved = client.post(f"/api/entries/{entry['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    again = client.post(f"/api/entries/{entry['id']}/approve")
    assert again.status_code == 409


def test_entry_with_unmapped_account_needs_review_and_cannot_be_approved():
    created = client.post("/api/propose", json={"document": MAPPING_GAP_DOC})
    entry = created.json()
    assert entry["status"] == "needs_review"
    assert any("unknown account" in issue for issue in entry["issues"])

    blocked = client.post(f"/api/entries/{entry['id']}/approve")
    assert blocked.status_code == 409


def test_reject_moves_entry_out_of_pending():
    entry = client.post("/api/propose", json={"document": VALID_DOC}).json()
    rejected = client.post(f"/api/entries/{entry['id']}/reject")
    assert rejected.json()["status"] == "rejected"
    assert client.post(f"/api/entries/{entry['id']}/approve").status_code == 409


def test_unreadable_document_returns_422():
    response = client.post("/api/propose", json={"document": "Date: 2026-10-01\nDescription: no amount here"})
    assert response.status_code == 422


def test_unknown_entry_returns_404():
    assert client.post("/api/entries/does-not-exist/approve").status_code == 404
