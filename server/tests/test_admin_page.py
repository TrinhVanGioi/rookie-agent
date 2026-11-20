"""Task 10.6: what the admin page needs from the server: the page itself, a preview of edits, the list with the highest risk."""

from __future__ import annotations

from tests.test_edit import learn


def test_the_page_is_served_without_a_login_and_is_in_vietnamese(client):
    page = client.get("/admin/")
    assert page.status_code == 200 and "Quản trị luồng" in page.text
    script = client.get("/admin/admin.js")
    assert script.status_code == 200 and client.get("/admin/admin.css").status_code == 200
    assert "Hành động vượt quyền" in script.text and "Tự phục hồi khi chỉ đổi giao diện" in script.text
    assert "Quay về bản này" in script.text and "Nhật ký thích nghi" in page.text
    assert "Xóa luồng" in page.text
    assert "cdn" not in page.text.lower() and "http://" not in page.text and "https://" not in page.text      # offline network


def test_a_preview_shows_the_edited_flow_and_keeps_nothing(client):
    flow = learn(client)
    reply = client.post(f"/workflows/{flow}/versions/1/edit/preview", json={"ops": [{"op": "label", "node": "g2", "label": "Tìm"}]})
    assert reply.status_code == 200 and reply.json()["api"][1]["group_label"] == "Tìm"
    assert [r["version"] for r in client.get("/workflows").json()["workflows"]] == [1]
    refused = client.post(f"/workflows/{flow}/versions/1/edit/preview", json={"ops": [{"op": "delete", "node": "g1"}]})
    assert refused.status_code == 422


def test_the_list_says_the_highest_risk_of_each_flow(client):
    flow = learn(client)                      # the Java transfer flow: its last step is money
    row = client.get("/workflows").json()["workflows"][0]
    assert row["id"] == flow and row["max_risk"] == "money"
