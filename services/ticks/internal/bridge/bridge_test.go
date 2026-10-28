package bridge

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// The bridge converts both timestamps with pandas before answering, so the
// wire format is an implementation detail of the layer in between. These are
// the shapes it has been seen to produce, plus the numeric forms it would
// produce if that layer changed.
func TestATimestampIsDecodedInEveryShapeTheBridgeMightSendIt(t *testing.T) {
	want := time.Date(2026, 1, 2, 3, 4, 5, 123_000_000, time.UTC).UnixMilli()
	for _, raw := range []string{
		`"2026-01-02T03:04:05.123000"`,
		`"2026-01-02T03:04:05.123"`,
		`"2026-01-02T03:04:05.123Z"`,
		`"2026-01-02T03:04:05.123+00:00"`,
	} {
		var got jsonTime
		if err := json.Unmarshal([]byte(raw), &got); err != nil {
			t.Fatalf("%s: %v", raw, err)
		}
		if !got.known || got.ms != want {
			t.Errorf("%s decoded to %d, want %d", raw, got.ms, want)
		}
	}
}

// **A naive stamp has to be read as UTC, not as local time.** The bridge sends
// no offset. Parsing it in the local zone would shift every row in the corpus
// by the offset of whichever machine ran the backfill, which is the kind of
// error that survives every test that only checks row counts.
func TestANaiveStampIsUTCRatherThanWhereverThisRan(t *testing.T) {
	var got jsonTime
	if err := json.Unmarshal([]byte(`"2026-01-02T00:00:00"`), &got); err != nil {
		t.Fatal(err)
	}
	if want := time.Date(2026, 1, 2, 0, 0, 0, 0, time.UTC).UnixMilli(); got.ms != want {
		t.Errorf("got %d, want %d - parsed in the local zone?", got.ms, want)
	}
}

// Seconds and milliseconds are told apart by magnitude, so a change in the
// layer in between cannot silently move every tick to 1973 or to the year 5138.
func TestANumericStampIsReadInTheRightUnit(t *testing.T) {
	cases := map[string]int64{
		`1767323045`:     1767323045000, // seconds
		`1767323045123`:  1767323045123, // milliseconds
		`1767323045.123`: 1767323045123, // seconds, fractional
	}
	for raw, want := range cases {
		var got jsonTime
		if err := json.Unmarshal([]byte(raw), &got); err != nil {
			t.Fatalf("%s: %v", raw, err)
		}
		if got.ms != want {
			t.Errorf("%s decoded to %d, want %d", raw, got.ms, want)
		}
	}
}

func TestAnUnparseableStampIsAnErrorRatherThanTheEpoch(t *testing.T) {
	var got jsonTime
	if err := json.Unmarshal([]byte(`"the second of January"`), &got); err == nil {
		t.Fatal("a stamp that matches no layout must not quietly become 1970")
	}
}

// 404 is how the bridge says "no tick data", which is a fact about the period
// rather than a failed request - and the difference decides whether the
// backfill records the day as absent or as failed.
func TestNoTickDataIsAnEmptyAnswerRatherThanAnError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"detail":"No tick data found"}`))
	}))
	defer server.Close()

	ticks, err := New(server.URL, "", time.Second).TicksRange(
		context.Background(), "EURUSD", time.Now(), time.Now().Add(time.Hour))
	if err != nil {
		t.Fatalf("404 must not be an error: %v", err)
	}
	if ticks != nil {
		t.Errorf("got %d ticks, want none", len(ticks))
	}
}

func TestTheRequestCarriesTheKeyAndTheRange(t *testing.T) {
	var gotKey, gotFrom, gotTo, gotFlags string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey = r.Header.Get("X-API-Key")
		gotFrom = r.URL.Query().Get("date_from")
		gotTo = r.URL.Query().Get("date_to")
		gotFlags = r.URL.Query().Get("flags")
		_, _ = w.Write([]byte(`[]`))
	}))
	defer server.Close()

	from := time.Date(2026, 3, 4, 0, 0, 0, 0, time.UTC)
	if _, err := New(server.URL, "shhh", time.Second).TicksRange(
		context.Background(), "EURUSD", from, from.AddDate(0, 0, 1)); err != nil {
		t.Fatal(err)
	}
	if gotKey != "shhh" {
		t.Errorf("key %q", gotKey)
	}
	if gotFrom != "2026-03-04T00:00:00" || gotTo != "2026-03-05T00:00:00" {
		t.Errorf("range %q..%q", gotFrom, gotTo)
	}
	// ALL rather than INFO: INFO drops the trade-flag bits, and the contract
	// keeps them precisely to show they are absent on this broker.
	if gotFlags != "ALL" {
		t.Errorf("flags %q, want ALL", gotFlags)
	}
}

// A row the bridge sends with no usable millisecond stamp falls back to the
// second-resolution copy, and a row with neither is dropped rather than
// written at the epoch - where it would sort to the front and read as the
// oldest tick on the feed.
func TestARowWithNoUsableStampIsDroppedNotStampedNineteenSeventy(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`[
          {"time_msc": null, "time": "2026-01-02T03:04:05", "bid": 1.1, "ask": 1.2, "flags": 6},
          {"time_msc": null, "time": null, "bid": 9.9, "ask": 9.9, "flags": 6},
          {"time_msc": "2026-01-02T03:04:06.500", "time": "2026-01-02T03:04:06", "bid": 1.3, "ask": 1.4, "flags": 2}
        ]`))
	}))
	defer server.Close()

	ticks, err := New(server.URL, "", time.Second).TicksRange(
		context.Background(), "EURUSD", time.Now(), time.Now().Add(time.Hour))
	if err != nil {
		t.Fatal(err)
	}
	if len(ticks) != 2 {
		t.Fatalf("got %d ticks, want 2 - the stampless row should be dropped", len(ticks))
	}
	if want := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC).UnixMilli(); ticks[0].TimeMsc != want {
		t.Errorf("fallback stamp %d, want %d", ticks[0].TimeMsc, want)
	}
	if ticks[1].Flags != 2 {
		t.Errorf("flags %d - the bid-only revision must survive the round trip", ticks[1].Flags)
	}
}
