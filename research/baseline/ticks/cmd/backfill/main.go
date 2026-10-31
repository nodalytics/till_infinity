// Command backfill fills the tick corpus from the MT5 terminal, a day at a
// time, and can be re-run.
//
//	backfill -root ~/tick-data -from 2025-01-01 -to 2026-10-01
//
// Reads TRADING_MT5_URL and TRADING_MT5_API_KEY, the same two variables the
// desk's own broker client reads, so a box configured to trade is already
// configured to backfill.
//
// # One request at a time
//
// There is a single terminal behind the bridge and every call goes through its
// IPC pipe. The bridge's stream router says it plainly - six parallel sweeps
// against one terminal is not six times the throughput - and this is also the
// process that starved the API into timing out when it was asked for a million
// bars per chart. So this walks feeds and days serially, with a pause between
// requests, and the way to go faster is a wider range per request rather than
// more of them at once.
//
// # Empty is not zero
//
// History downloads on demand, so a period the terminal has never been asked
// for comes back empty until it has fetched it - the first deep request can
// fail and a retry succeed. An empty answer is therefore recorded as a day
// that is *absent*, never as an empty file, and the run reports how many were
// empty so that "the market was closed" and "the terminal has not downloaded
// it yet" stay distinguishable. See `shared/contracts/ticks.md`.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/nodalytics/till_infinity/services/ticks/internal/bridge"
	"github.com/nodalytics/till_infinity/services/ticks/internal/store"
)

// feeds is the desk's FX majors and crosses: the set `statespace-surprise`
// trades, which is what the first corpus is for. Lowercase desk names; the
// broker's symbol is the upper-cased form, and that mapping lives here because
// this is the component that talks to the broker.
var feeds = []string{
	"eurusd", "gbpusd", "usdjpy", "usdcad", "usdchf", "audusd", "nzdusd",
	"eurgbp", "eurjpy", "gbpjpy", "eurchf", "audjpy", "chfjpy", "euraud",
}

func symbolOf(feed string) string { return strings.ToUpper(feed) }

func main() {
	var (
		root    = flag.String("root", "tick-data", "Where the corpus lives.")
		fromDay = flag.String("from", "", "First UTC day, YYYY-MM-DD.")
		toDay   = flag.String("to", "", "Last UTC day, exclusive, YYYY-MM-DD. Default: today.")
		only    = flag.String("feeds", "", "Comma-separated feeds. Default: the FX majors and crosses.")
		pause   = flag.Duration("pause", 500*time.Millisecond, "Wait between requests, to leave the terminal usable.")
		timeout = flag.Duration("timeout", 5*time.Minute, "Per-request timeout. Generous: history downloads on demand.")
		retries = flag.Int("retries", 2, "Retries per feed-day on a transport or bridge error.")
		dry     = flag.Bool("dry-run", false, "Say what would be fetched and stop.")
	)
	flag.Parse()

	url := os.Getenv("TRADING_MT5_URL")
	if url == "" {
		log.Fatal("TRADING_MT5_URL is not set - there is no bridge to read")
	}
	if *fromDay == "" {
		log.Fatal("-from is required: a backfill with no start would walk to 1970")
	}

	from, err := time.ParseInLocation(time.DateOnly, *fromDay, time.UTC)
	if err != nil {
		log.Fatalf("-from: %v", err)
	}
	to := time.Now().UTC().Truncate(24 * time.Hour)
	if *toDay != "" {
		if to, err = time.ParseInLocation(time.DateOnly, *toDay, time.UTC); err != nil {
			log.Fatalf("-to: %v", err)
		}
	}
	if !from.Before(to) {
		log.Fatalf("-from %s is not before -to %s", from.Format(time.DateOnly), to.Format(time.DateOnly))
	}

	wanted := feeds
	if *only != "" {
		wanted = nil
		for _, f := range strings.Split(*only, ",") {
			if f = strings.ToLower(strings.TrimSpace(f)); f != "" {
				wanted = append(wanted, f)
			}
		}
	}

	// Ctrl-C stops after the day in flight rather than mid-write, so the
	// corpus is always a set of complete days.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	client := bridge.New(url, os.Getenv("TRADING_MT5_API_KEY"), *timeout)

	var written, skipped, empty, failed, rows int
	started := time.Now()

	for _, feed := range wanted {
		for day := from; day.Before(to); day = day.AddDate(0, 0, 1) {
			if ctx.Err() != nil {
				break
			}
			if store.Done(*root, feed, day) {
				skipped++
				continue
			}
			if *dry {
				fmt.Printf("would fetch %s %s\n", feed, day.Format(time.DateOnly))
				written++
				continue
			}

			ticks, err := fetch(ctx, client, feed, day, *retries, *pause)
			if err != nil {
				log.Printf("%s %s: %v", feed, day.Format(time.DateOnly), err)
				failed++
				continue
			}
			if len(ticks) == 0 {
				// Absent, not empty. A weekend and an undownloaded month look
				// the same from here, and writing either would be a lie.
				empty++
				continue
			}
			if _, err := store.Write(*root, feed, day, ticks); err != nil {
				log.Printf("%s %s: %v", feed, day.Format(time.DateOnly), err)
				failed++
				continue
			}
			written++
			rows += len(ticks)
		}
	}

	fmt.Printf("%d day(s) written, %d row(s), %d skipped, %d empty, %d failed in %s\n",
		written, rows, skipped, empty, failed, time.Since(started).Round(time.Second))
	if failed > 0 {
		os.Exit(1)
	}
}

// fetch asks for one UTC day, retrying a transport or bridge error.
//
// The retry is here rather than inside the client because the thing worth
// retrying is this *day*: the first request for a period the terminal has not
// downloaded can fail while the download it triggered goes on, so asking again
// a moment later is a different question from asking the same one twice.
func fetch(ctx context.Context, c *bridge.Client, feed string, day time.Time, retries int, pause time.Duration) ([]bridge.Tick, error) {
	var lastErr error
	for attempt := 0; attempt <= retries; attempt++ {
		if attempt > 0 {
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(time.Duration(attempt) * 2 * time.Second):
			}
		}
		ticks, err := c.TicksRange(ctx, symbolOf(feed), day, day.AddDate(0, 0, 1))
		if err == nil {
			time.Sleep(pause)
			return ticks, nil
		}
		lastErr = err
	}
	return nil, lastErr
}
