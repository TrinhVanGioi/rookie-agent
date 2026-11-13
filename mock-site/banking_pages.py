"""HTML for the CIF, transfer and approval screens of the mock site.

Each page talks to the JSON API with fetch and updates the DOM in place, so the
recorder sees content changes without a URL change.
"""

from layout import page

# Shared by the three pages: JSON helpers and safe table rendering.
_SCRIPT_HELPERS = """
  const status = document.getElementById("status");
  async function call(method, url, body) {
    const response = await fetch(url, {
      method,
      headers: body ? {"Content-Type": "application/json"} : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? "Dữ liệu nhập không hợp lệ." : data.detail;
      throw new Error(detail || "Có lỗi xảy ra.");
    }
    return data;
  }
  function cell(tr, text, className) {
    const td = document.createElement("td");
    td.textContent = text;
    if (className) td.className = className;
    tr.appendChild(td);
    return td;
  }
"""


def cif_page() -> str:
    return page(
        "Khách hàng (CIF)",
        """<h1>Khách hàng (CIF)</h1>
<h2>Tra cứu</h2>
<div class="bar">
  <div><label for="cif-query">Số CIF hoặc CCCD</label><br><input id="cif-query" name="cif_query" inputmode="numeric"></div>
  <button id="btn-cif-search" type="button">Tra cứu CIF</button>
</div>
<table id="tbl-cif">
  <thead><tr><th>Số CIF</th><th>Họ và tên</th><th>Số CCCD</th><th>Số điện thoại</th><th>Tài khoản</th><th>Số dư</th></tr></thead>
  <tbody></tbody>
</table>
<h2>Mở CIF mới</h2>
<form id="form-open-cif" class="stack">
  <p><label for="cif-name">Họ và tên</label><br><input id="cif-name" name="customer_name"></p>
  <p><label for="cif-id-number">Số CCCD</label><br><input id="cif-id-number" name="id_number" inputmode="numeric"></p>
  <p><label for="cif-phone">Số điện thoại</label><br><input id="cif-phone" name="phone" inputmode="tel"></p>
  <button id="btn-open-cif" type="submit">Mở CIF</button>
</form>
<p id="status" role="status"></p>
<script>"""
        + _SCRIPT_HELPERS
        + """
  const body = document.querySelector("#tbl-cif tbody");
  function show(customers) {
    body.replaceChildren();
    for (const customer of customers) {
      for (const account of customer.accounts) {
        const tr = document.createElement("tr");
        cell(tr, customer.cif); cell(tr, customer.name); cell(tr, customer.id_number);
        cell(tr, customer.phone); cell(tr, account.number); cell(tr, account.balance, "num");
        body.appendChild(tr);
      }
    }
  }
  document.getElementById("btn-cif-search").addEventListener("click", async () => {
    try {
      const query = document.getElementById("cif-query").value;
      const data = await call("GET", "/api/cif?q=" + encodeURIComponent(query));
      show(data.customers);
      status.textContent = data.customers.length ? "Tìm thấy khách hàng." : "Không tìm thấy khách hàng.";
    } catch (error) { status.textContent = error.message; }
  });
  document.getElementById("form-open-cif").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const customer = await call("POST", "/api/cif", {
        name: document.getElementById("cif-name").value,
        id_number: document.getElementById("cif-id-number").value,
        phone: document.getElementById("cif-phone").value,
      });
      show([customer]);
      status.textContent = "Đã mở CIF " + customer.cif + ".";
      event.target.reset();
    } catch (error) { status.textContent = error.message; }
  });
</script>""",
    )


def transfer_page() -> str:
    return page(
        "Chuyển tiền",
        """<h1>Lập lệnh chuyển tiền</h1>
<form id="form-transfer" class="stack">
  <p><label for="tf-from">Tài khoản chuyển</label><br><input id="tf-from" name="from_account" inputmode="numeric"></p>
  <p><label for="tf-to">Tài khoản nhận</label><br><input id="tf-to" name="to_account" inputmode="numeric"></p>
  <p><label for="tf-amount">Số tiền</label><br><input id="tf-amount" name="amount" inputmode="numeric"></p>
  <p><label for="tf-note">Nội dung</label><br><input id="tf-note" name="note"></p>
  <button id="btn-submit-transfer" type="submit">Gửi duyệt</button>
</form>
<p id="status" role="status"></p>
<script>"""
        + _SCRIPT_HELPERS
        + """
  document.getElementById("form-transfer").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const order = await call("POST", "/api/transfers", {
        from_account: document.getElementById("tf-from").value,
        to_account: document.getElementById("tf-to").value,
        amount: Number(document.getElementById("tf-amount").value),
        note: document.getElementById("tf-note").value,
      });
      status.textContent = "Đã gửi lệnh " + order.id + ", chờ phê duyệt.";
      event.target.reset();
    } catch (error) { status.textContent = error.message; }
  });
</script>""",
    )


def approval_page() -> str:
    return page(
        "Phê duyệt",
        """<h1>Hàng chờ phê duyệt</h1>
<button id="btn-refresh-queue" type="button">Tải lại</button>
<table id="tbl-queue">
  <thead><tr><th>Mã lệnh</th><th>Tài khoản chuyển</th><th>Tài khoản nhận</th><th>Số tiền</th><th>Nội dung</th><th>Người lập</th><th>Thao tác</th></tr></thead>
  <tbody></tbody>
</table>
<p id="status" role="status"></p>
<script>"""
        + _SCRIPT_HELPERS
        + """
  const body = document.querySelector("#tbl-queue tbody");
  function action(td, label, order, verb) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-label", label + " lệnh " + order.id);
    button.addEventListener("click", async () => {
      try {
        const result = await call("POST", "/api/transfers/" + order.id + "/" + verb);
        await load();
        status.textContent = "Lệnh " + result.id + (verb === "approve" ? " đã duyệt." : " đã từ chối.");
      } catch (error) { status.textContent = error.message; }
    });
    td.appendChild(button);
  }
  async function load() {
    const data = await call("GET", "/api/transfers?status=pending");
    body.replaceChildren();
    for (const order of data.transfers) {
      const tr = document.createElement("tr");
      cell(tr, order.id); cell(tr, order.from_account); cell(tr, order.to_account);
      cell(tr, order.amount, "num"); cell(tr, order.note); cell(tr, order.maker);
      const td = cell(tr, "");
      action(td, "Duyệt", order, "approve");
      action(td, "Từ chối", order, "reject");
      body.appendChild(tr);
    }
    status.textContent = data.transfers.length + " lệnh chờ duyệt";
  }
  document.getElementById("btn-refresh-queue").addEventListener("click", load);
  load().catch((error) => { status.textContent = error.message; });
</script>""",
    )
