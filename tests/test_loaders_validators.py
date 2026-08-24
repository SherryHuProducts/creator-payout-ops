from datetime import date
from decimal import Decimal

import pytest

from creator_payout_ops.loaders import CSVLoadError, load_creator_agreements, load_platform_orders
from creator_payout_ops.models import CreatorAgreement, PlatformOrder, SettlementStatus
from creator_payout_ops.validators import validate_creator_agreements, validate_platform_orders


def test_order_loader_parses_decimal_date_and_enum(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text("order_id,creator_id,creator_username,order_date,gross_sales,actual_commission,refund_amount,settlement_status\nO1,C1,user,2025-01-02,10.25,2.05,0.00,SETTLED\n")
    order = load_platform_orders(path)[0]
    assert order.gross_sales == Decimal("10.25")
    assert order.order_date == date(2025, 1, 2)
    assert order.settlement_status is SettlementStatus.SETTLED


def test_agreement_loader_blank_end_date_and_bool(tmp_path):
    path = tmp_path / "agreements.csv"
    path.write_text("creator_id,creator_name,creator_share_rate,effective_date,end_date,active\nC1,Creator A,0.625,2025-01-01,,true\n")
    agreement = load_creator_agreements(path)[0]
    assert agreement.creator_share_rate == Decimal("0.625")
    assert agreement.end_date is None
    assert agreement.active is True


def test_loader_rejects_invalid_enum(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text("order_id,creator_id,creator_username,order_date,gross_sales,actual_commission,refund_amount,settlement_status\nO1,C1,user,2025-01-02,10,2,0,UNKNOWN\n")
    with pytest.raises(CSVLoadError, match="invalid settlement_status"):
        load_platform_orders(path)


def make_order(order_id="O1", gross="10", commission="2"):
    return PlatformOrder(order_id, "C1", "user", date(2025, 1, 1), Decimal(gross), Decimal(commission), Decimal("0"), SettlementStatus.SETTLED)


def test_duplicate_order_detection():
    issues = validate_platform_orders([make_order(), make_order()])
    assert [issue.issue_type for issue in issues] == ["duplicate_order_id"]


def test_negative_monetary_values():
    issues = validate_platform_orders([make_order(gross="-1", commission="-2")])
    assert {issue.field for issue in issues} == {"gross_sales", "actual_commission"}


@pytest.mark.parametrize("rate", ["-0.01", "1.01"])
def test_invalid_creator_share_rate(rate):
    agreement = CreatorAgreement("C1", "Creator A", Decimal(rate), date(2025, 1, 1), None, True)
    assert validate_creator_agreements([agreement])[0].issue_type == "out_of_range"


def test_invalid_agreement_date_range():
    agreement = CreatorAgreement("C1", "Creator A", Decimal("0.5"), date(2025, 2, 1), date(2025, 1, 31), True)
    assert validate_creator_agreements([agreement])[0].issue_type == "invalid_date_range"
