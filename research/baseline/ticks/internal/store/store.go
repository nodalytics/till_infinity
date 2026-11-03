// Package store writes the tick corpus to disk.
//
// The layout and schema are `shared/contracts/ticks.md`. Everything here
// exists to keep two properties the contract promises: a file that exists is a
// day that is complete, and an empty day is absent rather than empty.
package store

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/parquet-go/parquet-go"

	"github.com/nodalytics/till_infinity/services/ticks/internal/bridge"
)

// Name is the file inside each day's partition.
const Name = "ticks.parquet"

// Path is where a feed's day lives under root.
func Path(root, feed string, day time.Time) string {
	return filepath.Join(root,
		"feed="+feed,
		"date="+day.UTC().Format(time.DateOnly),
		Name)
}

// Done reports whether this feed-day has already been written.
//
// A zero-length file is **not** done. A process killed between creating the
// file and writing it leaves one behind, and treating that as complete is how
// a resumable backfill writes a permanent hole.
func Done(root, feed string, day time.Time) bool {
	info, err := os.Stat(Path(root, feed, day))
	return err == nil && info.Size() > 0
}

// Write puts one feed-day on disk, sorted, and returns the path.
//
// **Written to a temporary file and renamed.** A reader that walks the corpus
// while a backfill is running must never see a half-written partition, and
// rename within a directory is atomic on every filesystem this will meet.
func Write(root, feed string, day time.Time, ticks []bridge.Tick) (string, error) {
	if len(ticks) == 0 {
		return "", fmt.Errorf("refusing to write an empty day for %s %s - the contract says absent, not empty",
			feed, day.UTC().Format(time.DateOnly))
	}

	sort.Slice(ticks, func(i, j int) bool { return ticks[i].TimeMsc < ticks[j].TimeMsc })

	final := Path(root, feed, day)
	if err := os.MkdirAll(filepath.Dir(final), 0o755); err != nil {
		return "", err
	}

	tmp, err := os.CreateTemp(filepath.Dir(final), ".ticks-*.parquet")
	if err != nil {
		return "", err
	}
	defer os.Remove(tmp.Name())

	// Zstd because this compresses extremely well and the corpus is the thing
	// that will grow: a quote stream is a narrow row repeated millions of
	// times, and `flags` and the zeroed trade columns are nearly constant.
	writer := parquet.NewGenericWriter[bridge.Tick](tmp, parquet.Compression(&parquet.Zstd))
	if _, err := writer.Write(ticks); err != nil {
		tmp.Close()
		return "", fmt.Errorf("writing %s: %w", final, err)
	}
	if err := writer.Close(); err != nil {
		tmp.Close()
		return "", fmt.Errorf("closing the parquet writer for %s: %w", final, err)
	}
	if err := tmp.Close(); err != nil {
		return "", err
	}
	if err := os.Rename(tmp.Name(), final); err != nil {
		return "", err
	}
	return final, nil
}
