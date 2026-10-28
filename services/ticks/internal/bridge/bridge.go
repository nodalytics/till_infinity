// Package bridge talks to the MT5 HTTP bridge.
//
// The terminal is Windows-only and runs under Wine behind a FastAPI process
// (see the metatrader-terminal repository). Everything here goes through
// `/api/v1/symbols/ticks/{symbol}/range`, which returns what the terminal
// actually recorded for a period rather than what it happens to be quoting
// now - the distinction `shared/contracts/ticks.md` explains.
package bridge

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// Tick is one quote update, as the corpus stores it.
type Tick struct {
	TimeMsc    int64   `parquet:"time_msc"`
	Bid        float64 `parquet:"bid"`
	Ask        float64 `parquet:"ask"`
	Last       float64 `parquet:"last"`
	Volume     int64   `parquet:"volume"`
	VolumeReal float64 `parquet:"volume_real"`
	Flags      int32   `parquet:"flags"`
}

// Client is one terminal behind one bridge.
//
// **Not safe for concurrent range requests, by design.** There is a single
// terminal at the other end and every call goes through its IPC pipe; the
// bridge's own stream router says the same thing about parallel sweeps. A
// caller that wants to go faster should ask for a wider range, not more
// sockets.
type Client struct {
	base string
	key  string
	http *http.Client
}

// New returns a client for a bridge at base, authenticating with key.
//
// The timeout is generous because it has to be: the terminal downloads history
// on demand, so the first request for an untouched period pays for the
// download. A 30-second timeout reads that as a failure and retries into the
// same wait.
func New(base, key string, timeout time.Duration) *Client {
	if timeout <= 0 {
		timeout = 5 * time.Minute
	}
	return &Client{
		base: strings.TrimRight(base, "/"),
		key:  key,
		http: &http.Client{Timeout: timeout},
	}
}

// apiTick mirrors one record as the bridge serialises it.
//
// The bridge converts `time` and `time_msc` with pandas before answering, so
// they arrive as ISO-8601 strings rather than numbers. That is an
// implementation detail of the layer in between, not of MT5, so it is decoded
// defensively: a string in any of several shapes, or a number, both become the
// same instant.
type apiTick struct {
	TimeMsc    jsonTime `json:"time_msc"`
	Time       jsonTime `json:"time"`
	Bid        float64  `json:"bid"`
	Ask        float64  `json:"ask"`
	Last       float64  `json:"last"`
	Volume     int64    `json:"volume"`
	VolumeReal float64  `json:"volume_real"`
	Flags      int32    `json:"flags"`
}

// jsonTime decodes an instant written as an ISO-8601 string or as an epoch
// number, and keeps it in milliseconds.
type jsonTime struct {
	ms    int64
	known bool
}

var layouts = []string{
	"2006-01-02T15:04:05.000000",
	"2006-01-02T15:04:05.000",
	"2006-01-02T15:04:05",
	time.RFC3339Nano,
	time.RFC3339,
}

func (t *jsonTime) UnmarshalJSON(raw []byte) error {
	text := strings.Trim(string(raw), `"`)
	if text == "" || text == "null" {
		return nil
	}
	// A bare number is epoch milliseconds if it is large enough to be one, and
	// seconds otherwise. The threshold is 1e11, which is the year 5138 in
	// seconds and 1973 in milliseconds - no real tick is ambiguous.
	if raw[0] != '"' {
		n, err := strconv.ParseFloat(text, 64)
		if err != nil {
			return fmt.Errorf("tick time %q is neither a string nor a number: %w", text, err)
		}
		if n < 1e11 {
			n *= 1000
		}
		t.ms, t.known = int64(n), true
		return nil
	}
	for _, layout := range layouts {
		// **UTC, explicitly.** The bridge sends no offset, and parsing a naive
		// stamp with `time.Parse` would be UTC while `time.ParseInLocation`
		// with the local zone would silently shift every row by the offset of
		// whichever machine ran the backfill.
		if when, err := time.ParseInLocation(layout, text, time.UTC); err == nil {
			t.ms, t.known = when.UnixMilli(), true
			return nil
		}
	}
	return fmt.Errorf("tick time %q matches no known layout", text)
}

// TicksRange returns every tick the terminal holds for symbol in [from, to).
//
// An empty result is not an error and not an empty day: it means the terminal
// has nothing for that period, which may be a closed market or may be history
// it has not downloaded yet. The caller decides which, and
// `shared/contracts/ticks.md` says why that matters.
func (c *Client) TicksRange(ctx context.Context, symbol string, from, to time.Time) ([]Tick, error) {
	query := url.Values{}
	query.Set("date_from", from.UTC().Format("2006-01-02T15:04:05"))
	query.Set("date_to", to.UTC().Format("2006-01-02T15:04:05"))
	query.Set("flags", "ALL")

	endpoint := fmt.Sprintf("%s/api/v1/symbols/ticks/%s/range?%s", c.base, url.PathEscape(symbol), query.Encode())
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	if c.key != "" {
		req.Header.Set("X-API-Key", c.key)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%s %s: %w", symbol, from.Format(time.DateOnly), err)
	}
	defer resp.Body.Close()

	// 404 is the bridge's way of saying "no tick data", which is a fact about
	// the period rather than a failure of the request.
	if resp.StatusCode == http.StatusNotFound {
		return nil, nil
	}
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 400))
		return nil, fmt.Errorf("%s %s: bridge returned %d: %s",
			symbol, from.Format(time.DateOnly), resp.StatusCode, strings.TrimSpace(string(body)))
	}

	var raw []apiTick
	if err := json.NewDecoder(resp.Body).Decode(&raw); err != nil {
		return nil, fmt.Errorf("%s %s: decoding the answer: %w", symbol, from.Format(time.DateOnly), err)
	}

	ticks := make([]Tick, 0, len(raw))
	for _, r := range raw {
		stamp := r.TimeMsc
		if !stamp.known {
			// Fall back to the second-resolution copy rather than writing a
			// row stamped 1970, which sorts to the front of the corpus and
			// would be read as the oldest tick on the feed.
			stamp = r.Time
		}
		if !stamp.known {
			continue
		}
		ticks = append(ticks, Tick{
			TimeMsc:    stamp.ms,
			Bid:        r.Bid,
			Ask:        r.Ask,
			Last:       r.Last,
			Volume:     r.Volume,
			VolumeReal: r.VolumeReal,
			Flags:      r.Flags,
		})
	}
	return ticks, nil
}
