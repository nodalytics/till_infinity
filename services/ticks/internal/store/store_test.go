package store

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/parquet-go/parquet-go"

	"github.com/nodalytics/till_infinity/services/ticks/internal/bridge"
)

var day = time.Date(2026, 3, 4, 0, 0, 0, 0, time.UTC)

func some() []bridge.Tick {
	return []bridge.Tick{
		{TimeMsc: 1767323045500, Bid: 1.0855, Ask: 1.08555, Flags: 6},
		{TimeMsc: 1767323045100, Bid: 1.0854, Ask: 1.08555, Flags: 2},
		{TimeMsc: 1767323045900, Bid: 1.0854, Ask: 1.08560, Flags: 4},
	}
}

func TestThePathIsTheHivePartitionTheContractPromises(t *testing.T) {
	got := Path("/corpus", "eurusd", day)
	want := filepath.Join("/corpus", "feed=eurusd", "date=2026-03-04", "ticks.parquet")
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

// **A zero-length file is not a finished day.** A process killed between
// creating the file and writing it leaves one behind, and a resumable backfill
// that counts it as done writes a permanent hole into the corpus.
func TestAnEmptyFileIsNotAFinishedDay(t *testing.T) {
	root := t.TempDir()
	if Done(root, "eurusd", day) {
		t.Error("an absent day must not read as done")
	}

	path := Path(root, "eurusd", day)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	if Done(root, "eurusd", day) {
		t.Error("a zero-length file must not read as done")
	}

	if _, err := Write(root, "eurusd", day, some()); err != nil {
		t.Fatal(err)
	}
	if !Done(root, "eurusd", day) {
		t.Error("a written day must read as done")
	}
}

// The contract says an empty day is absent, never an empty file, because a
// weekend and a month the terminal has not downloaded look identical from here.
func TestWritingAnEmptyDayIsRefused(t *testing.T) {
	if _, err := Write(t.TempDir(), "eurusd", day, nil); err == nil {
		t.Fatal("an empty day must be refused rather than written")
	}
}

// Sorted on the way out, so a reader can rely on it rather than re-sorting
// every file - and so a merge of two days is a concatenation.
func TestTheRowsComeBackSortedAndWholeIncludingFlags(t *testing.T) {
	root := t.TempDir()
	path, err := Write(root, "eurusd", day, some())
	if err != nil {
		t.Fatal(err)
	}

	rows, err := parquet.ReadFile[bridge.Tick](path)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 3 {
		t.Fatalf("got %d rows, want 3", len(rows))
	}
	for i := 1; i < len(rows); i++ {
		if rows[i-1].TimeMsc > rows[i].TimeMsc {
			t.Fatalf("row %d is out of order: %d then %d", i, rows[i-1].TimeMsc, rows[i].TimeMsc)
		}
	}
	// `flags` is the whole reason this corpus can say anything about
	// direction - a bid-only revision is bit 2 without bit 4 - so a round trip
	// that loses it loses the only observable bars cannot express.
	if rows[0].Flags != 2 || rows[1].Flags != 6 || rows[2].Flags != 4 {
		t.Errorf("flags came back as %d/%d/%d, want 2/6/4",
			rows[0].Flags, rows[1].Flags, rows[2].Flags)
	}
	if rows[0].Bid != 1.0854 || rows[0].Ask != 1.08555 {
		t.Errorf("prices did not survive: %v", rows[0])
	}
}

// Nothing half-written is ever visible: the file is built under a temporary
// name and renamed, so a reader walking the corpus during a backfill sees
// either a complete day or no day.
func TestNoTemporaryFileIsLeftBehind(t *testing.T) {
	root := t.TempDir()
	if _, err := Write(root, "eurusd", day, some()); err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(filepath.Dir(Path(root, "eurusd", day)))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Name() != Name {
		var names []string
		for _, e := range entries {
			names = append(names, e.Name())
		}
		t.Errorf("partition holds %v, want just %s", names, Name)
	}
}
