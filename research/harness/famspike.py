"""The two model tables `famreport` puts past the log window: spike_next, and direction by family."""
import io, contextlib
from research.harness import famreport
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    famreport.main()
lines = buf.getvalue().splitlines()
start = next(i for i, l in enumerate(lines) if "spike_next on tick bars" in l)
end = next(i for i, l in enumerate(lines) if "the census" in l)
print("\n".join(lines[start:end]))
d = next(i for i, l in enumerate(lines) if "direction and volatility on wall-clock" in l)
print("\n".join(lines[d:d + 14]))
