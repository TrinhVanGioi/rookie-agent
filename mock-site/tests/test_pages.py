import pytest
from fastapi.testclient import TestClient

from app import DEMO_PASSWORD, DEMO_USER, SEED, UI_IDS, app
from data import generate_reports


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def logged_in(client):
    response = client.post("/login", data={"username": DEMO_USER, "password": DEMO_PASSWORD})
    assert response.status_code == 303
    return client


def test_report_page_requires_login(client):
    response = client.get("/baocao/cuoingay")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_wrong_password_is_rejected(client):
    response = client.post("/login", data={"username": DEMO_USER, "password": "sai"})
    assert response.status_code == 401
    assert "session" not in response.cookies


def test_api_requires_login(client):
    assert client.get("/api/report?source=a&date=2026-11-10").status_code == 401


def test_report_page_uses_original_ids_by_default(logged_in):
    html = logged_in.get("/baocao/cuoingay").text
    for element_id in UI_IDS["v1"].values():
        assert f'id="{element_id}"' in html
    assert "Tìm kiếm" in html


def test_new_ui_switch_changes_ids_and_button_name(logged_in):
    response = logged_in.get("/ui/toggle")
    assert response.status_code == 303
    html = logged_in.get("/baocao/cuoingay").text
    for element_id in UI_IDS["v2"].values():
        assert f'id="{element_id}"' in html
    for element_id in UI_IDS["v1"].values():
        assert f'id="{element_id}"' not in html
    assert "Tra cứu" in html
    assert "Tìm kiếm" not in html


def test_new_ui_switch_toggles_back(logged_in):
    logged_in.get("/ui/toggle")
    logged_in.get("/ui/toggle")
    html = logged_in.get("/baocao/cuoingay").text
    assert f'id="{UI_IDS["v1"]["search"]}"' in html


def test_api_returns_generated_rows(logged_in):
    report_a, report_b = generate_reports("2026-11-10", seed=SEED)
    assert logged_in.get("/api/report?source=a&date=2026-11-10").json()["rows"] == report_a
    assert logged_in.get("/api/report?source=b&date=2026-11-10").json()["rows"] == report_b


def test_api_filters_by_account(logged_in):
    report_a, _ = generate_reports("2026-11-10", seed=SEED)
    account = report_a[0]["account"]
    rows = logged_in.get(f"/api/report?source=a&date=2026-11-10&account={account}").json()["rows"]
    assert rows
    assert all(row["account"] == account for row in rows)


def test_api_rejects_bad_source_and_date(logged_in):
    assert logged_in.get("/api/report?source=c&date=2026-11-10").status_code == 422
    assert logged_in.get("/api/report?source=a&date=10-11-2026").status_code == 422


def test_csv_export_has_header_and_all_rows(logged_in):
    report_a, _ = generate_reports("2026-11-10", seed=SEED)
    lines = logged_in.get("/api/report.csv?source=a&date=2026-11-10").text.strip().splitlines()
    assert lines[0] == "id,account,customer,amount,status"
    assert len(lines) == len(report_a) + 1
