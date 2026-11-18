"""Tasks 6.6 and 6.7: the synthetic payment orders are read offline and split into the fields of docs/design.md 6.2."""

import pytest

from rookie_agent.voucher import extract
from rookie_agent.voucher.reader import SAMPLES, SampleReader, UnreadableDocument


def read(name):
    return extract.extract(SampleReader().read((SAMPLES / f"{name}.png").read_bytes()))


@pytest.mark.parametrize("words,number", [
    ("Năm triệu đồng chẵn", 5_000_000), ("Một trăm hai mươi lăm triệu đồng", 125_000_000),
    ("Hai triệu ba trăm linh năm nghìn đồng", 2_305_000), ("Mười lăm triệu đồng chẵn", 15_000_000),
    ("Bảy triệu năm trăm nghìn đồng", 7_500_000), ("Hai mươi mốt nghìn", 21_000), ("Một tỷ không trăm linh tư triệu", 1_004_000_000),
])
def test_amounts_in_words(words, number):
    assert extract.words_to_number(words) == number


def test_there_are_five_samples_and_one_has_amounts_that_differ():
    assert len(list(SAMPLES.glob("*.png"))) == 5
    assert [read(f"unc-0{i}")["ready"] for i in range(1, 6)] == [True, True, True, False, False]


@pytest.mark.parametrize("name,acct,amount", [("unc-01", "9876543210", "5.000.000"), ("unc-02", "4444555566", "125.000.000"),
                                              ("unc-03", "7777888899", "2.305.000")])
def test_the_fields_are_split_out(name, acct, amount):
    fields = {f["name"]: f for f in read(name)["fields"]}
    assert fields["so_tai_khoan_nhan"]["value"] == acct and fields["so_tien"]["value"] == amount
    assert all(f["value"] and not f["problem"] for f in fields.values())


def test_a_faint_field_and_amounts_that_differ_are_marked():
    faint = {f["name"]: f for f in read("unc-04")["fields"]}
    assert faint["so_tai_khoan_nhan"]["confidence"] == 0.62 and faint["so_tai_khoan_nhan"]["problem"]
    differ = {f["name"]: f for f in read("unc-05")["fields"]}
    assert "không khớp" in differ["so_tien"]["problem"] and "không khớp" in differ["so_tien_bang_chu"]["problem"]


def test_a_picture_that_is_not_a_sample_is_refused_offline():
    with pytest.raises(UnreadableDocument):
        SampleReader().read(b"not a sample")


def test_the_confirmation_needs_every_field_and_equal_amounts():
    fields = read("unc-05")["fields"]
    assert extract.check_confirmed(fields) == ["Số tiền bằng số và bằng chữ không khớp"]
    for f in fields:
        if f["name"] == "so_tien_bang_chu":
            f["value"] = "Bảy triệu năm trăm nghìn đồng"
    assert extract.check_confirmed(fields) == []
