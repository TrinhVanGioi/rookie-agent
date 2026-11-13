"""Synthetic customers (CIF) and a maker-checker transfer queue for the mock site.

Everything is generated from a seed and kept in memory. No real customer data,
no real money: an approved transfer only changes numbers in this process.
"""

import random
import re
from typing import Literal, TypedDict

from data import _FAMILY_NAMES, _GIVEN_NAMES, _MIDDLE_NAMES

CUSTOMER_COUNT = 20
ACCOUNT_PATTERN = re.compile(r"^\d{12}$")
ID_NUMBER_PATTERN = re.compile(r"^\d{12}$")
PHONE_PATTERN = re.compile(r"^0\d{9}$")

TransferStatus = Literal["pending", "approved", "rejected"]


class Account(TypedDict):
    number: str
    balance: int


class Customer(TypedDict):
    cif: str
    name: str
    id_number: str
    phone: str
    accounts: list[Account]


class Transfer(TypedDict):
    id: str
    from_account: str
    to_account: str
    amount: int
    note: str
    status: TransferStatus
    maker: str
    checker: str | None


class BankError(Exception):
    """A rejected operation. `status` is the HTTP status the API should return."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _digits(rng: random.Random, length: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(length))


def generate_customers(seed: int, count: int = CUSTOMER_COUNT) -> list[Customer]:
    """Same seed gives the same customers."""
    rng = random.Random(f"customers:{seed}")
    customers: list[Customer] = []
    for index in range(1, count + 1):
        customers.append(
            {
                # Index-based prefixes keep CIF and account numbers unique.
                "cif": f"{index:03d}{_digits(rng, 5)}",
                "name": " ".join(
                    [rng.choice(_FAMILY_NAMES), rng.choice(_MIDDLE_NAMES), rng.choice(_GIVEN_NAMES)]
                ),
                "id_number": f"{index:03d}{_digits(rng, 9)}",
                "phone": "09" + _digits(rng, 8),
                "accounts": [
                    {
                        "number": f"{index:03d}{slot}{_digits(rng, 8)}",
                        "balance": rng.randrange(1_000_000, 2_000_000_000),
                    }
                    for slot in range(rng.choice([1, 1, 2]))
                ],
            }
        )
    return customers


class Bank:
    def __init__(self, seed: int) -> None:
        self._rng = random.Random(f"bank:{seed}")
        self.customers: list[Customer] = generate_customers(seed)
        self.transfers: list[Transfer] = []

    def _account(self, number: str) -> Account | None:
        for customer in self.customers:
            for account in customer["accounts"]:
                if account["number"] == number:
                    return account
        return None

    def find_customers(self, query: str) -> list[Customer]:
        query = query.strip()
        return [c for c in self.customers if query in (c["cif"], c["id_number"])]

    def open_cif(self, name: str, id_number: str, phone: str) -> Customer:
        name = name.strip()
        if not name:
            raise BankError(422, "Thiếu họ và tên")
        if not ID_NUMBER_PATTERN.match(id_number):
            raise BankError(422, "Số CCCD phải gồm 12 chữ số")
        if not PHONE_PATTERN.match(phone):
            raise BankError(422, "Số điện thoại phải gồm 10 chữ số, bắt đầu bằng 0")
        if any(c["id_number"] == id_number for c in self.customers):
            raise BankError(409, "Số CCCD này đã có CIF")
        index = len(self.customers) + 1
        customer: Customer = {
            "cif": f"{index:03d}{_digits(self._rng, 5)}",
            "name": name,
            "id_number": id_number,
            "phone": phone,
            "accounts": [{"number": f"{index:03d}0{_digits(self._rng, 8)}", "balance": 0}],
        }
        self.customers.append(customer)
        return customer

    def create_transfer(
        self, maker: str, from_account: str, to_account: str, amount: int, note: str
    ) -> Transfer:
        source = self._account(from_account)
        if source is None:
            raise BankError(422, "Tài khoản chuyển không tồn tại")
        if not ACCOUNT_PATTERN.match(to_account):
            raise BankError(422, "Tài khoản nhận phải gồm 12 chữ số")
        if to_account == from_account:
            raise BankError(422, "Tài khoản nhận trùng tài khoản chuyển")
        if amount <= 0:
            raise BankError(422, "Số tiền phải lớn hơn 0")
        if amount > source["balance"]:
            raise BankError(422, "Số dư không đủ")
        transfer: Transfer = {
            "id": f"LCT{len(self.transfers) + 1:05d}",
            "from_account": from_account,
            "to_account": to_account,
            "amount": amount,
            "note": note,
            "status": "pending",
            "maker": maker,
            "checker": None,
        }
        self.transfers.append(transfer)
        return transfer

    def list_transfers(self, status: TransferStatus | None = None) -> list[Transfer]:
        return [t for t in self.transfers if status is None or t["status"] == status]

    def decide_transfer(self, transfer_id: str, checker: str, approve: bool) -> Transfer:
        transfer = next((t for t in self.transfers if t["id"] == transfer_id), None)
        if transfer is None:
            raise BankError(404, "Không tìm thấy lệnh")
        if transfer["status"] != "pending":
            raise BankError(409, "Lệnh đã được xử lý")
        if transfer["maker"] == checker:
            raise BankError(403, "Không được duyệt lệnh do chính mình lập")
        if approve:
            source = self._account(transfer["from_account"])
            if source is None or source["balance"] < transfer["amount"]:
                raise BankError(409, "Số dư không đủ tại thời điểm duyệt")
            source["balance"] -= transfer["amount"]
            target = self._account(transfer["to_account"])
            if target is not None:
                target["balance"] += transfer["amount"]
        transfer["status"] = "approved" if approve else "rejected"
        transfer["checker"] = checker
        return transfer
