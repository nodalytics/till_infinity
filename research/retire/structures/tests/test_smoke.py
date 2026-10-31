from click.testing import CliRunner

from till_infinity.cli import main


def test_cli_lists_the_prices_group():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "prices" in result.output


def test_prices_symbols_shows_the_defaults():
    result = CliRunner().invoke(main, ["prices", "symbols"])
    assert result.exit_code == 0
    assert "tradingview" in result.output
    assert "yahoo" in result.output
    for name in ("eurusd", "gbpusd", "gold", "btc"):
        assert name in result.output


def test_prices_symbols_resolves_an_ad_hoc_ticker():
    result = CliRunner().invoke(main, ["prices", "symbols", "NASDAQ:AAPL"])
    assert result.exit_code == 0
    assert "NASDAQ:AAPL" in result.output
