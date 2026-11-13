"""Shared HTML shell for the mock site pages."""

from html import escape

NAV = """<nav aria-label="Chức năng">
  <a id="nav-baocao" href="/baocao/cuoingay">Báo cáo cuối ngày</a> ·
  <a id="nav-cif" href="/cif">Khách hàng (CIF)</a> ·
  <a id="nav-chuyentien" href="/chuyentien">Chuyển tiền</a> ·
  <a id="nav-pheduyet" href="/pheduyet">Phê duyệt</a> ·
  <a id="logout" href="/logout">Đăng xuất</a>
</nav>"""


def page(title: str, body: str, nav: bool = True) -> str:
    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 24px; }}
  nav {{ margin-bottom: 16px; }}
  .bar {{ display: flex; gap: 12px; align-items: end; margin: 12px 0; }}
  .bar.reverse {{ flex-direction: row-reverse; justify-content: flex-end; }}
  .tabs button[aria-selected="true"] {{ font-weight: bold; }}
  form.stack p {{ margin: 8px 0; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #999; padding: 4px 8px; }}
  td.num {{ text-align: right; }}
  .error {{ color: #b00020; }}
</style>
</head>
<body>
{NAV if nav else ""}
{body}
</body>
</html>"""
