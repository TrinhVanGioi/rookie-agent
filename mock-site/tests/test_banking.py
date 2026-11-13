import pytest

from banking import Bank, BankError, generate_customers


def test_same_seed_gives_same_customers():
    assert generate_customers(seed=7) == generate_customers(seed=7)
    assert generate_customers(seed=7) != generate_customers(seed=8)


def test_customers_have_unique_cif_and_accounts():
    customers = generate_customers(seed=42)
    assert len({c["cif"] for c in customers}) == len(customers)
    accounts = [a["number"] for c in customers for a in c["accounts"]]
    assert len(set(accounts)) == len(accounts)
    assert all(len(c["cif"]) == 8 and len(c["id_number"]) == 12 for c in customers)


@pytest.fixture
def bank():
    return Bank(seed=42)


def test_find_customer_by_cif_or_id_number(bank):
    customer = bank.customers[0]
    assert bank.find_customers(customer["cif"]) == [customer]
    assert bank.find_customers(customer["id_number"]) == [customer]
    assert bank.find_customers("00000000") == []


def test_open_cif_adds_customer_and_rejects_duplicate_id_number(bank):
    created = bank.open_cif(name="Nguyễn Văn Thử", id_number="001099000001", phone="0900000001")
    assert bank.find_customers(created["cif"]) == [created]
    assert len(created["accounts"]) == 1
    with pytest.raises(BankError) as error:
        bank.open_cif(name="Người Khác", id_number="001099000001", phone="0900000002")
    assert error.value.status == 409


def test_transfer_is_pending_until_approved_by_someone_else(bank):
    source = bank.customers[0]["accounts"][0]
    target = bank.customers[1]["accounts"][0]
    before = source["balance"]
    order = bank.create_transfer("gdv01", source["number"], target["number"], 1_000, "test")
    assert order["status"] == "pending"
    assert source["balance"] == before  # nothing moves before approval
    assert [o["id"] for o in bank.list_transfers("pending")] == [order["id"]]

    approved = bank.decide_transfer(order["id"], "ksv01", approve=True)
    assert approved["status"] == "approved"
    assert approved["checker"] == "ksv01"
    assert source["balance"] == before - 1_000
    assert bank.list_transfers("pending") == []


def test_cannot_approve_own_transfer(bank):
    source = bank.customers[0]["accounts"][0]
    target = bank.customers[1]["accounts"][0]
    order = bank.create_transfer("ksv01", source["number"], target["number"], 1_000, "")
    with pytest.raises(BankError) as error:
        bank.decide_transfer(order["id"], "ksv01", approve=True)
    assert error.value.status == 403
    assert bank.list_transfers("pending")[0]["id"] == order["id"]


def test_rejected_transfer_moves_no_money(bank):
    source = bank.customers[0]["accounts"][0]
    target = bank.customers[1]["accounts"][0]
    before = source["balance"]
    order = bank.create_transfer("gdv01", source["number"], target["number"], 1_000, "")
    assert bank.decide_transfer(order["id"], "ksv01", approve=False)["status"] == "rejected"
    assert source["balance"] == before
    with pytest.raises(BankError):  # already decided
        bank.decide_transfer(order["id"], "ksv01", approve=True)


@pytest.mark.parametrize("amount", [0, -5])
def test_transfer_rejects_bad_amount(bank, amount):
    source = bank.customers[0]["accounts"][0]
    target = bank.customers[1]["accounts"][0]
    with pytest.raises(BankError):
        bank.create_transfer("gdv01", source["number"], target["number"], amount, "")


def test_transfer_rejects_unknown_account_same_account_and_overdraft(bank):
    source = bank.customers[0]["accounts"][0]
    target = bank.customers[1]["accounts"][0]
    with pytest.raises(BankError):
        bank.create_transfer("gdv01", "999999999999", target["number"], 1_000, "")
    with pytest.raises(BankError):
        bank.create_transfer("gdv01", source["number"], source["number"], 1_000, "")
    with pytest.raises(BankError):
        bank.create_transfer("gdv01", source["number"], target["number"], source["balance"] + 1, "")
