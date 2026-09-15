import pytest
from conftest import EVIDENCE

from kitchen_ledger import operations
from kitchen_ledger.operations import DomainError


def buy_packaging(conn, package_price, packages=1):
    return operations.register_purchase(
        conn, ingredient_name="Marmita 500 ml", kind="packaging", packages=packages, package_quantity="50",
        package_unit="un", package_price=package_price, price_source="owner_confirmed", source_url=None,
        dish_id=None, evidence=EVIDENCE,
    )


def remaining(conn):
    return operations.get_state_summary(conn)["budget_remaining_display"]


def test_overrun_is_refused_until_the_owner_raises_the_budget(conn):
    assert remaining(conn) == "R$ 80,00"
    buy_packaging(conn, "25.00")
    assert remaining(conn) == "R$ 55,00"

    with pytest.raises(DomainError) as error:
        buy_packaging(conn, "60.00")
    assert error.value.code == "budget_exceeded"
    assert error.value.details["shortfall_display"] == "R$ 5,00"
    assert remaining(conn) == "R$ 55,00"  # the refused purchase wrote nothing

    operations.adjust_budget(conn, "10", "Dona Maria aumentou o orçamento em R$ 10")
    buy_packaging(conn, "60.00")
    assert remaining(conn) == "R$ 5,00"


def test_budget_pays_whole_packages(conn):
    buy_packaging(conn, "5.00", packages=3)
    assert remaining(conn) == "R$ 65,00"


def test_zero_budget_adjustment_is_rejected(conn):
    with pytest.raises(DomainError) as error:
        operations.adjust_budget(conn, "0", EVIDENCE)
    assert error.value.code == "invalid_delta"
