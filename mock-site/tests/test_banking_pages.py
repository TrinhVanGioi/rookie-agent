import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import CHECKER_PASSWORD, CHECKER_USER, DEMO_PASSWORD, DEMO_USER, app


def _login(username: str, password: str) -> TestClient:
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"username": username, "password": password}).status_code == 303
    return client


@pytest.fixture(autouse=True)
def fresh_bank():
    app_module.reset_bank()


@pytest.fixture
def maker():
    return _login(DEMO_USER, DEMO_PASSWORD)


@pytest.fixture
def checker():
    return _login(CHECKER_USER, CHECKER_PASSWORD)


def _accounts():
    customers = app_module.bank.customers
    return customers[0]["accounts"][0]["number"], customers[1]["accounts"][0]["number"]


def _transfer(client: TestClient, amount: int = 1_000):
    source, target = _accounts()
    return client.post(
        "/api/transfers",
        json={"from_account": source, "to_account": target, "amount": amount, "note": "thử"},
    )


@pytest.mark.parametrize("path", ["/cif", "/chuyentien", "/pheduyet"])
def test_pages_require_login(path):
    response = TestClient(app, follow_redirects=False).get(path)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize("path", ["/api/cif?q=1", "/api/transfers"])
def test_apis_require_login(path):
    assert TestClient(app).get(path).status_code == 401


@pytest.mark.parametrize(
    ("path", "labels"),
    [
        ("/cif", ["Số CIF hoặc CCCD", "Họ và tên", "Mở CIF"]),
        ("/chuyentien", ["Tài khoản chuyển", "Tài khoản nhận", "Số tiền", "Gửi duyệt"]),
        ("/pheduyet", ["Hàng chờ phê duyệt"]),
    ],
)
def test_pages_show_their_form_labels(maker, path, labels):
    html = maker.get(path).text
    for label in labels:
        assert label in html


def test_cif_lookup_returns_synthetic_customer(maker):
    customer = app_module.bank.customers[0]
    assert maker.get(f"/api/cif?q={customer['cif']}").json()["customers"] == [customer]
    assert maker.get("/api/cif?q=00000000").json()["customers"] == []


def test_open_cif_then_duplicate_is_conflict(maker):
    payload = {"name": "Trần Thị Thử", "id_number": "001099000009", "phone": "0900000009"}
    created = maker.post("/api/cif", json=payload)
    assert created.status_code == 201
    cif = created.json()["cif"]
    assert maker.get(f"/api/cif?q={cif}").json()["customers"][0]["name"] == "Trần Thị Thử"
    assert maker.post("/api/cif", json=payload).status_code == 409


def test_open_cif_rejects_bad_id_number(maker):
    payload = {"name": "Trần Thị Thử", "id_number": "123", "phone": "0900000009"}
    assert maker.post("/api/cif", json=payload).status_code == 422


def test_maker_transfer_shows_in_checker_queue_and_can_be_approved(maker, checker):
    created = _transfer(maker)
    assert created.status_code == 201
    order = created.json()
    assert order["status"] == "pending"
    assert order["maker"] == DEMO_USER

    queue = checker.get("/api/transfers?status=pending").json()["transfers"]
    assert [o["id"] for o in queue] == [order["id"]]

    approved = checker.post(f"/api/transfers/{order['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert checker.get("/api/transfers?status=pending").json()["transfers"] == []


def test_checker_cannot_approve_own_transfer(checker):
    order = _transfer(checker).json()
    assert checker.post(f"/api/transfers/{order['id']}/approve").status_code == 403


def test_maker_role_cannot_approve_or_reject(maker, checker):
    order = _transfer(checker).json()
    assert maker.post(f"/api/transfers/{order['id']}/approve").status_code == 403
    assert maker.post(f"/api/transfers/{order['id']}/reject").status_code == 403


def test_checker_can_reject(maker, checker):
    order = _transfer(maker).json()
    assert checker.post(f"/api/transfers/{order['id']}/reject").json()["status"] == "rejected"


def test_bad_transfer_is_rejected(maker):
    assert _transfer(maker, amount=0).status_code == 422
    assert _transfer(maker, amount=10**15).status_code == 422
    assert maker.post("/api/transfers/khong-co/approve").status_code in (403, 404)
