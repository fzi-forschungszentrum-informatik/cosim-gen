import pytest

from cosim.codegen.dts_overlay import _reg_cells


@pytest.mark.parametrize(
    "value, num_cells, expected",
    [
        (0x64000000, 1, "0x64000000"),
        (0x64000000, 2, "0x0 0x64000000"),
        (0x1_0000_0100, 2, "0x1 0x100"),
    ],
)
def test_reg_cells(value, num_cells, expected):
    assert _reg_cells(value, num_cells) == expected


def test_reg_cells_overflow():
    with pytest.raises(RuntimeError, match="doesn't fit"):
        _reg_cells(0x1_0000_0000, 1)
