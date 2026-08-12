from datetime import UTC, datetime

import pytest

from till_infinity.news import HIGH, LOW, MEDIUM, parse_importance, parse_number, parse_time
from till_infinity.news.calendar import parse_forexfactory, parse_tradingview
from till_infinity.news.headlines import category_for, parse_headlines
from till_infinity.news.models import Event, clean, digest
from till_infinity.news.rss import parse_feed
from till_infinity.news.source import PermanentError

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Dollar firms ahead of CPI</title>
    <link>https://example.com/a</link>
    <guid>guid-a</guid>
    <pubDate>Wed, 12 Aug 2026 19:28:00 GMT</pubDate>
    <description>&lt;p&gt;The &lt;b&gt;dollar&lt;/b&gt;   rose.&lt;/p&gt;</description>
  </item>
  <item><title>No link here</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Gold extends gains</title>
    <link href="https://example.com/gold"/>
    <id>atom-1</id>
    <published>2026-08-12T18:00:00Z</published>
    <summary>Spot gold rose.</summary>
  </entry>
</feed>"""


def test_rss_items_become_articles():
    first, second = parse_feed("forexlive", RSS)
    assert first.id == "guid-a"
    assert first.title == "Dollar firms ahead of CPI"
    assert first.url == "https://example.com/a"
    assert first.summary == "The dollar rose."  # tags stripped, spaces collapsed
    assert first.published == datetime(2026, 8, 12, 19, 28, tzinfo=UTC).timestamp()
    # No link and no guid, so an id is derived rather than dropping the story.
    assert second.id
    assert second.url == ""


def test_atom_entries_parse_too():
    (article,) = parse_feed("fxstreet", ATOM)
    assert article.id == "atom-1"
    assert article.url == "https://example.com/gold"  # href attribute, not body
    assert article.published == datetime(2026, 8, 12, 18, tzinfo=UTC).timestamp()


def test_an_entry_without_a_title_is_skipped():
    feed = b'<?xml version="1.0"?><rss><channel><item><link>x</link></item></channel></rss>'
    assert parse_feed("x", feed) == []


def test_malformed_feed_is_permanent():
    with pytest.raises(PermanentError, match="malformed"):
        parse_feed("broken", b"not xml at all")


FF_ROWS = [
    {
        "title": "GDP m/m",
        "country": "GBP",
        "date": "2026-08-13T02:00:00-04:00",
        "impact": "High",
        "forecast": "0.0%",
        "previous": "0.1%",
        "actual": "",
    },
    {
        "title": "Bank Lending y/y",
        "country": "JPY",
        "date": "2026-08-09T19:50:00-04:00",
        "impact": "Low",
        "actual": "2.9%",
    },
    {"title": "Ignored", "country": "NZD", "date": "2026-08-13T02:00:00-04:00", "impact": "Low"},
]


def test_forexfactory_rows_become_events():
    events = parse_forexfactory(FF_ROWS, currencies=("GBP", "JPY"))
    assert [e.country for e in events] == ["GBP", "JPY"]  # NZD filtered out
    gdp = events[0]
    assert gdp.source == "forexfactory"
    assert gdp.importance == HIGH
    assert gdp.time == datetime(2026, 8, 13, 6, tzinfo=UTC).timestamp()
    assert not gdp.released  # actual is empty until the print lands
    assert events[1].released


def test_forexfactory_ids_are_stable_across_polls():
    """The id has to survive re-polling, or every pass would look like new rows."""
    first = parse_forexfactory(FF_ROWS, currencies=("GBP",))[0]
    released = dict(FF_ROWS[0], actual="0.3%")
    second = parse_forexfactory([released], currencies=("GBP",))[0]
    assert first.id == second.id
    assert second.released


def test_forexfactory_rejects_a_non_list():
    with pytest.raises(PermanentError, match="expected a list"):
        parse_forexfactory({"error": "nope"})


TV_OK = {
    "status": "ok",
    "result": [
        {
            "id": "420445",
            "title": "PPI MoM",
            "country": "US",
            "date": "2026-08-13T12:30:00.000Z",
            "importance": 1,
            "actual": None,
            "forecast": 0.2,
            "previous": -0.3,
            "unit": "%",
            "period": "Jul",
        }
    ],
}


def test_tradingview_calendar_rows_become_events():
    (event,) = parse_tradingview(TV_OK)
    assert (event.source, event.id, event.country) == ("tradingview", "420445", "US")
    assert event.importance == HIGH
    assert event.time == datetime(2026, 8, 13, 12, 30, tzinfo=UTC).timestamp()
    assert (event.forecast, event.previous, event.unit) == ("0.2", "-0.3", "%")


def test_tradingview_calendar_error_is_permanent():
    with pytest.raises(PermanentError):
        parse_tradingview({"status": "error"})


TV_NEWS = {
    "items": [
        {
            "id": "tag:reuters.com,2026:newsml_L1N44205J:0",
            "title": "Gold extends gains on softer dollar",
            "source": "Reuters",
            "published": 1786000000,
            "urgency": 2,
            "relatedSymbols": [{"symbol": "OANDA:XAUUSD"}, {"symbol": "TVC:GOLD"}],
            "storyPath": "/news/reuters.com,2026:newsml:0-gold/",
        },
        {"title": "", "id": "empty"},
    ]
}


def test_headlines_become_articles():
    (article,) = parse_headlines(TV_NEWS)  # the untitled item is skipped
    assert article.provider == "Reuters"
    assert article.symbols == ("OANDA:XAUUSD", "TVC:GOLD")
    assert article.url == "https://www.tradingview.com/news/reuters.com,2026:newsml:0-gold/"
    assert article.published == 1786000000.0
    assert article.urgency == 2


def test_headlines_fall_back_to_the_queried_symbol():
    payload = {"items": [{"id": "x", "title": "Something", "relatedSymbols": []}]}
    (article,) = parse_headlines(payload, fallback_symbol="OANDA:EURUSD")
    assert article.symbols == ("OANDA:EURUSD",)


def test_headlines_reject_a_bad_body():
    with pytest.raises(PermanentError):
        parse_headlines({"error": "nope"})


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("BINANCE:BTCUSDT", "crypto"),
        ("OANDA:XAUUSD", "forex"),
        ("PEPPERSTONE:EURUSD", "forex"),
        ("NASDAQ:AAPL", "stock"),
        ("AAPL", "stock"),
    ],
)
def test_category_inferred_from_the_venue(symbol, expected):
    assert category_for(symbol) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("High", HIGH), ("medium", MEDIUM), ("Holiday", LOW), (1, HIGH), (0, MEDIUM), (-1, LOW)],
)
def test_importance_normalised_across_providers(value, expected):
    assert parse_importance(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("220K", 220_000.0),
        ("1.5M", 1_500_000.0),
        ("-1.2%", -1.2),
        ("3.5", 3.5),
        ("", None),
        ("n/a", None),
        (None, None),
        (7, 7.0),
    ],
)
def test_number_parsing_handles_suffixes(value, expected):
    assert parse_number(value) == expected


def test_time_parsing_accepts_every_shape_these_feeds_send():
    iso = datetime(2026, 8, 13, 12, 30, tzinfo=UTC).timestamp()
    assert parse_time("2026-08-13T12:30:00.000Z") == iso
    assert parse_time("2026-08-13T08:30:00-04:00") == iso
    assert parse_time("Thu, 13 Aug 2026 12:30:00 GMT") == iso
    assert parse_time(iso) == iso
    assert parse_time("") is None
    assert parse_time("whenever") is None


def test_surprise_is_actual_minus_forecast():
    event = Event(source="x", id="1", title="CPI", actual="220K", forecast="215K")
    assert event.surprise == pytest.approx(5000.0)
    assert Event(source="x", id="2", title="CPI", forecast="1").surprise is None


def test_clean_and_digest():
    assert clean("<p>a   &amp; b</p>") == "a & b"
    assert digest("a", None, 1) == digest("a", None, 1)
    assert digest("a") != digest("b")


IMF_XML = b"""<?xml version='1.0' encoding='UTF-8'?>
<message:StructureSpecificData
    xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message">
  <message:DataSet>
    <Series COUNTRY="USA" INDICATOR="IRFCLDT1_IRFCL54_USD" SECTOR="S1XS1311"
            FREQUENCY="M" SCALE="6">
      <Obs TIME_PERIOD="2026-M06" OBS_VALUE="251000000000"/>
      <Obs TIME_PERIOD="2026-M07" OBS_VALUE="252708091800"/>
      <Obs TIME_PERIOD="2026-M08" OBS_VALUE=""/>
    </Series>
  </message:DataSet>
</message:StructureSpecificData>"""


def test_imf_dataset_becomes_observations():
    from till_infinity.news.imf import parse_dataset

    rows = parse_dataset(IMF_XML)
    assert len(rows) == 2  # the empty observation is dropped
    latest = rows[-1]
    assert latest.country == "USA"
    assert latest.indicator == "IRFCLDT1_IRFCL54_USD"
    assert latest.series == "USA.IRFCLDT1_IRFCL54_USD.S1XS1311.M"
    assert latest.period == "2026-M07"
    assert latest.time == datetime(2026, 7, 1, tzinfo=UTC).timestamp()


def test_imf_values_are_not_rescaled():
    """SCALE=6 is provenance, not a multiplier — US reserves are $252.7bn, and
    applying the exponent would report $252.7 quadrillion."""
    from till_infinity.news.imf import parse_dataset

    latest = parse_dataset(IMF_XML)[-1]
    assert latest.scale == 6
    assert latest.value == 252_708_091_800.0
    assert 2e11 < latest.value < 3e11
    assert "scaled" not in latest.to_dict()


def test_imf_malformed_body_is_permanent():
    from till_infinity.news.imf import parse_dataset

    with pytest.raises(PermanentError, match="malformed"):
        parse_dataset(b"<not xml")


def test_imf_key_uses_iso3_with_open_middle_dimensions():
    """`US...M` returns a valid but empty document; only `USA...M` has data."""
    from till_infinity.news import Settings
    from till_infinity.news.imf import ImfSource

    source = ImfSource(Settings(data_dir="/tmp"), countries=("USA",))
    assert source.key("USA") == "USA...M"
    assert source.key("USA").count(".") == 3  # COUNTRY.INDICATOR.SECTOR.FREQUENCY


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        ("2026-M07", datetime(2026, 7, 1, tzinfo=UTC)),
        ("2026-Q3", datetime(2026, 7, 1, tzinfo=UTC)),
        ("2026", datetime(2026, 1, 1, tzinfo=UTC)),
    ],
)
def test_sdmx_periods_map_to_the_start_of_the_period(period, expected):
    from till_infinity.news import parse_period

    assert parse_period(period) == expected.timestamp()


def test_imf_start_period_counts_months_back():
    from till_infinity.news.imf import start_period

    assert start_period(0, now=datetime(2026, 8, 12, tzinfo=UTC)) == "2026-08"
    assert start_period(1, now=datetime(2026, 1, 12, tzinfo=UTC)) == "2025-12"
    assert start_period(18, now=datetime(2026, 8, 12, tzinfo=UTC)) == "2025-02"
