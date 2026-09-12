"""Kronos as a one-step forecaster, with the look-ahead closed off and the sampler made affordable.

This file is the plumbing under `kronos.py`. It exists because the two things
that decide whether a foundation-model score on this project means anything are
both *implementation* questions, not modelling questions:

1. **Where does the future enter?** A quantiser or a normalisation fitted across
   a split is a look-ahead, and it is the single most likely way this arm
   manufactures a false positive. The answer here is stated in code below and in
   `research/foundation.md`: the tokenizer is **frozen and causal by
   architecture** and every normalisation constant is computed inside the
   context window, which ends at `t`.
2. **What does one score cost?** The lab has no GPU and five other agents on it.
   The naive way to read Kronos - upstream's `auto_regressive_inference` with
   `sample_count=S` - decodes `S` full-length token sequences per scored row, and
   at S=64, ctx=128 that is ~32 GFLOP per row, which is hours per timeframe.
   The decoder is causal, so positions `0..T-1` are **identical across all S
   candidates**; caching their keys and values makes S free. `verify()` proves
   the cached path reproduces `tokenizer.decode` before anything is scored.

## Why the tokenizer cannot leak, and how that is checked rather than asserted

`KronosTokenizer` is an autoencoder whose encoder and decoder are stacks of
`TransformerBlock`, and `MultiHeadAttentionWithRoPE.forward` calls
`scaled_dot_product_attention(..., is_causal=True)`. **The code at position `t`
is a function of normalised bars `0..t` and nothing later.** The quantiser
itself - `BinarySphericalQuantizer` - is `sign(z)` on an L2-normalised
projection: there is no codebook, no fitted centroid, no running statistic. Its
weights come from Kronos's own pretraining corpus, which is real equities and
crypto and contains none of this study's rows.

That leaves exactly two places a future bar could enter, and both are closed:

* **The window normalisation.** `KronosPredictor.predict` takes mean and std over
  whatever frame it is handed. Hand it a frame that runs past `t` and every row
  in it is contaminated. `Reader.step` therefore takes windows that *end* at `t`
  and normalises inside them - the same convention upstream's own
  `finetune/dataset.py` uses, which z-scores on the lookback part only.
* **Fine-tuning.** Handled in `kronos.py`: the predictor is trained on the fold's
  train rows alone, refit per fold, and the tokenizer is never trained at all.

And `check_causality` does to the Kronos readout what `seqlab.check_causality`
does to the feature matrix: pokes a future bar by 5% and asserts the next-token
logits at earlier rows do not move a bit. It runs before any score is printed.

## The readout, and the bias it has to cancel

A 20-bit code over six channels is a coarse description of one bar. On a
Volatility 75 1h bar the true move is ~0.8% while the window's own close
dispersion over 128 bars is several percent, so **one bar of a GBM's motion is a
small fraction of a quantisation cell**. Comparing Kronos's decoded next close
against the *observed* close therefore measures reconstruction error, not
forecast error.

So every return is taken **relative to the tokenizer's own reconstruction of the
current bar**, which the context decode pass produces for free:

    r_hat = log(decoded next close / decoded current close)

Both sides carry the same quantisation bias and it cancels. `Reader.step`
returns the raw version too, and `kronos.py` reports both, because the gap
between them is a measurement of how much of the model's apparent motion is the
codebook rather than the market.

Volatility readouts carry a units problem the direction readout does not: a rank
AUC is scale-free, `seqlab.srel` is not. Kronos's mean absolute decoded return
is not on the same scale as `|log(c_{t+1}/c_t)|`, so scoring it raw would measure
a units mismatch. `kronos.py` fits **one scalar** per fold on **train rows only**
to put it on scale, which is one fewer free parameter than HAR is given.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from research.harness import seqlab

#: Upstream, vendored outside the git tree by `kronosboot.vendor`.
VENDOR = Path.home() / "till_infinity" / "vendor" / "Kronos"

#: Verified against the hub on 2026-09-12, not remembered. `mini` is the 4.1M
#: variant this study fine-tunes; it is the only one that pairs with the 2k
#: tokenizer, and pairing it with `Tokenizer-base` silently produces garbage
#: because the two differ in `group_size` alone and the shapes still line up.
PAIRS = {
    "mini": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k"),
    "small": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base"),
}

#: The six channels the tokenizer was trained on, in its order. `amount` is
#: turnover; upstream synthesises it as volume x mean price when it is absent,
#: and so does `frame`, so a feed without a turnover field is handled the way
#: upstream handles it rather than a way this file invented.
COLS = ("open", "high", "low", "close", "volume", "amount")

#: Upstream's normalisation clip, unchanged. It matters more here than upstream:
#: a synthetic feed can have a near-constant volume column, and `(x - m) / (s +
#: 1e-5)` on a constant column is a large number rather than a NaN. The clip is
#: what keeps that from reaching the encoder as a spike.
CLIP = 5.0

#: Five other agents share the lab and it has no GPU. Eight is the cap the study
#: runs under; `THREADS` lowers it when two of this study's own jobs overlap, so
#: the pair never takes more of the box than one job was allowed.
THREADS = int(os.environ.get("THREADS", 8))


def threads(n: int | None = None) -> None:
    n = THREADS if n is None else n
    torch.set_num_threads(n)
    os.environ.setdefault("OMP_NUM_THREADS", str(n))


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_pair(which: str = "mini", *, model_dir: str | None = None):
    """The frozen pair, on CPU, in eval mode.

    `model_dir` loads a fine-tuned predictor from disk instead of the hub. The
    tokenizer always comes from the hub: this study never trains it, which is
    what makes "the quantiser saw no test row" a statement about the code rather
    than a promise.
    """
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    from model import Kronos, KronosTokenizer  # noqa: PLC0415 - path set above

    model_id, tok_id = PAIRS[which]
    tokenizer = KronosTokenizer.from_pretrained(tok_id)
    model = Kronos.from_pretrained(model_dir if model_dir else model_id)
    tokenizer.eval()
    model.eval()
    for p in tokenizer.parameters():
        p.requires_grad_(False)
    return model, tokenizer


# --------------------------------------------------------------------------
# Bars -> the six channels and the five clock fields Kronos expects
# --------------------------------------------------------------------------


def frame(bars: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """`(n, 6)` channels and `(n, 5)` clock fields, in upstream's order.

    The clock fields are minute/hour/weekday/day/month, matching
    `model.kronos.calc_time_stamps`. They are integer indices into learned
    embeddings, so they must be the real calendar and not a row counter - which
    is also why the simulated controls in `gbm_like` are given the real feed's
    timestamps rather than their own.
    """
    o, h, low, c = (bars[k].astype(np.float64) for k in ("open", "high", "low", "close"))
    v = bars["volume"].astype(np.float64)
    amount = v * (o + h + low + c) / 4.0
    x = np.column_stack([o, h, low, c, v, amount]).astype(np.float32)

    stamps = [dt.datetime.fromtimestamp(float(t), dt.UTC) for t in bars["time"]]
    s = np.array([[s.minute, s.hour, s.weekday(), s.day, s.month] for s in stamps],
                 dtype=np.float32)
    return x, s


def windows(x: np.ndarray, stamp: np.ndarray, ends: np.ndarray, ctx: int):
    """Context windows `[t-ctx+1 .. t]` for each `t` in `ends`. Strictly causal."""
    ends = np.asarray(ends)
    if ends.min() < ctx - 1:
        raise ValueError(f"row {ends.min()} has no {ctx}-bar history")
    take = ends[:, None] - np.arange(ctx - 1, -1, -1)[None, :]
    return x[take], stamp[take]


# --------------------------------------------------------------------------
# The cached decoder. Everything below reproduces upstream exactly; `verify`
# is what makes that claim checkable rather than a comment.
# --------------------------------------------------------------------------


def _rotate_half(x: torch.Tensor) -> torch.Tensor:
    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat((-x2, x1), dim=-1)


def _rope_at(rotary, pos: int) -> tuple[torch.Tensor, torch.Tensor]:
    """`cos`/`sin` at one absolute position, by upstream's own formula.

    `RotaryPositionalEmbedding.forward` builds the table for positions
    `0..seq_len-1` from `q.shape[-2]`. A cached step has one query at absolute
    position `pos`, which that interface cannot express, so the table is rebuilt
    here from the same `inv_freq` buffer. Any drift between this and upstream
    shows up in `verify` as a reconstruction mismatch.
    """
    inv = rotary.inv_freq
    t = torch.tensor([float(pos)], dtype=inv.dtype, device=inv.device)
    freqs = torch.einsum("i,j->ij", t, inv)
    emb = torch.cat((freqs, freqs), dim=-1)
    return emb.cos()[None, None, :, :], emb.sin()[None, None, :, :]


def _block_context(block, x: torch.Tensor):
    """One `TransformerBlock` over the context, keeping post-RoPE keys and values."""
    sa = block.self_attn
    b, t, _ = x.shape
    residual = x
    h = block.norm1(x)
    q = sa.q_proj(h).view(b, t, sa.n_heads, sa.head_dim).transpose(1, 2)
    k = sa.k_proj(h).view(b, t, sa.n_heads, sa.head_dim).transpose(1, 2)
    v = sa.v_proj(h).view(b, t, sa.n_heads, sa.head_dim).transpose(1, 2)
    q, k = sa.rotary(q, k)
    out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
    out = out.transpose(1, 2).contiguous().view(b, t, sa.d_model)
    x = residual + sa.resid_dropout(sa.out_proj(out))
    return x + block.ffn(block.norm2(x)), k, v


def _block_step(block, x_new: torch.Tensor, k_ctx: torch.Tensor,
                v_ctx: torch.Tensor, pos: int) -> torch.Tensor:
    """`S` candidate tokens at absolute position `pos`, against a shared context.

    The `S` candidates are carried in the sequence dimension rather than the
    batch, so the context keys and values are **not** replicated `S` times. That
    is the whole economy of this file: at S=64, ctx=128 replication would cost
    three quarters of a gigabyte per layer-pair and turn a two-minute cell into
    an hour. Each candidate attends to the shared context plus its own key and
    nothing else, which is what causal attention would have given it, so the
    softmax is written out rather than handed to `scaled_dot_product_attention`.
    """
    sa = block.self_attn
    b, s, _ = x_new.shape
    residual = x_new
    h = block.norm1(x_new)
    q = sa.q_proj(h).view(b, s, sa.n_heads, sa.head_dim).transpose(1, 2)
    k = sa.k_proj(h).view(b, s, sa.n_heads, sa.head_dim).transpose(1, 2)
    v = sa.v_proj(h).view(b, s, sa.n_heads, sa.head_dim).transpose(1, 2)
    cos, sin = _rope_at(sa.rotary, pos)
    q = q * cos + _rotate_half(q) * sin
    k = k * cos + _rotate_half(k) * sin

    scale = 1.0 / math.sqrt(sa.head_dim)
    sc_ctx = torch.matmul(q, k_ctx.transpose(-1, -2)) * scale          # (b, H, s, T)
    sc_own = (q * k).sum(-1, keepdim=True) * scale                     # (b, H, s, 1)
    w = torch.softmax(torch.cat([sc_ctx, sc_own], dim=-1), dim=-1)
    out = torch.matmul(w[..., :-1], v_ctx) + w[..., -1:] * v
    out = out.transpose(1, 2).contiguous().view(b, s, sa.d_model)
    x = residual + sa.resid_dropout(sa.out_proj(out))
    return x + block.ffn(block.norm2(x))


def _cond_s2(model, context: torch.Tensor, cand_s1: torch.Tensor) -> torch.Tensor:
    """`decode_s2` for `S` candidates at the last position, in one pass.

    Reproduces `Kronos.decode_s2` under the shape upstream actually calls it
    with - one query position - rather than under the shape this batching would
    imply. The difference is the rotary: `MultiHeadCrossAttentionWithRoPE` builds
    its table from `q.shape[-2]`, so with upstream's single query it rotates by
    position 0, which is the identity, while a batch of `S` queries would rotate
    candidate `i` by position `i` and make the answer depend on the order the
    samples happened to be drawn in. Position 0 for every candidate is therefore
    not an approximation of upstream, it **is** upstream. `verify` checks it
    against `model.decode_s2` at S=1.
    """
    dep = model.dep_layer
    ca = dep.cross_attn
    b, ln, d = context.shape
    s = cand_s1.shape[1]
    sib = model.embedding.emb_s1(cand_s1)
    q = ca.q_proj(sib).view(b, s, ca.n_heads, ca.head_dim).transpose(1, 2)
    k = ca.k_proj(context).view(b, ln, ca.n_heads, ca.head_dim).transpose(1, 2)
    v = ca.v_proj(context).view(b, ln, ca.n_heads, ca.head_dim).transpose(1, 2)
    out = F.scaled_dot_product_attention(q, k, v)
    out = out.transpose(1, 2).contiguous().view(b, s, d)
    x2 = dep.norm(context[:, -1:, :] + ca.resid_dropout(ca.out_proj(out)))
    return model.head.cond_forward(x2)


def _nucleus(logits: torch.Tensor, top_k: int, top_p: float) -> torch.Tensor:
    """Upstream's `top_k_top_p_filtering`, on a 2-D block of logits."""
    if top_k > 0:
        kth = torch.topk(logits, min(top_k, logits.size(-1)))[0][..., -1, None]
        return logits.masked_fill(logits < kth, -float("inf"))
    if top_p < 1.0:
        srt, idx = torch.sort(logits, descending=True, dim=-1)
        cum = torch.cumsum(F.softmax(srt, dim=-1), dim=-1)
        drop = cum > top_p
        drop[..., 1:] = drop[..., :-1].clone()
        drop[..., 0] = False
        return logits.masked_fill(drop.scatter(1, idx, drop), -float("inf"))
    return logits


# --------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------


class Reader:
    """One-step-ahead next-bar samples for a batch of context windows.

    Every window ends at the row being scored. Nothing in `step` reads past it.
    """

    def __init__(self, model, tokenizer, *, ctx: int = 128, samples: int = 64,
                 temperature: float = 1.0, top_k: int = 0, top_p: float = 0.9,
                 seed: int = 11):
        self.model, self.tok = model, tokenizer
        self.ctx, self.samples = ctx, samples
        self.T, self.top_k, self.top_p = temperature, top_k, top_p
        self.gen = torch.Generator().manual_seed(seed)

    @torch.no_grad()
    def step(self, x_win: np.ndarray, stamp_win: np.ndarray,
             stats: tuple[np.ndarray, np.ndarray] | None = None) -> dict[str, np.ndarray]:
        """`x_win` is `(B, ctx, 6)` raw bars ending at the scored row.

        Returns, per window: the sampled next-bar log returns measured against
        the tokenizer's own reconstruction of the current bar (`r`), the same
        against the observed close (`r_raw`), the sampled log ranges, and the
        entropy of the next-token distribution - which is the model's own
        statement of how much it thinks it knows, and is free.
        """
        b, t, _ = x_win.shape
        if t != self.ctx:
            raise ValueError(f"window is {t} bars, reader is {self.ctx}")
        if stats is None:
            mean = x_win.mean(axis=1, keepdims=True)
            std = x_win.std(axis=1, keepdims=True)
        else:
            # Only `kronosleak` passes these, and only to build the contaminated
            # arms that measure what the causal default is worth.
            mean, std = stats
        xn = np.clip((x_win - mean) / (std + 1e-5), -CLIP, CLIP).astype(np.float32)

        xt = torch.from_numpy(xn)
        st = torch.from_numpy(stamp_win.astype(np.float32))

        s1, s2 = self.tok.encode(xt, half=True)
        s1_logits, context = self.model.decode_s1(s1, s2, st)
        last = s1_logits[:, -1, :].float()
        probs = F.softmax(_nucleus(last / self.T, self.top_k, self.top_p), dim=-1)
        cand1 = torch.multinomial(probs, self.samples, replacement=True, generator=self.gen)

        ent = -(F.softmax(last, -1) * F.log_softmax(last, -1)).sum(-1)

        s2_logits = _cond_s2(self.model, context, cand1).float()
        p2 = F.softmax(_nucleus((s2_logits / self.T).reshape(b * self.samples, -1),
                                self.top_k, self.top_p), dim=-1)
        cand2 = torch.multinomial(p2, 1, generator=self.gen).view(b, self.samples)

        # Context pass through the tokenizer's decoder, keeping keys and values.
        bits = self.tok.indices_to_bits([s1, s2], half=True)
        z = self.tok.post_quant_embed(bits)
        cache = []
        for layer in self.tok.decoder:
            z, k, v = _block_context(layer, z)
            cache.append((k, v))
        recon = self.tok.head(z)[:, -1, :]                       # (B, 6) normalised

        zc = self.tok.post_quant_embed(self.tok.indices_to_bits([cand1, cand2], half=True))
        for layer, (k, v) in zip(self.tok.decoder, cache, strict=True):
            zc = _block_step(layer, zc, k, v, pos=t)
        nxt = self.tok.head(zc)                                  # (B, S, 6) normalised

        m = torch.from_numpy(mean[:, 0, :].astype(np.float32))
        sd = torch.from_numpy(std[:, 0, :].astype(np.float32)) + 1e-5
        nxt = nxt * sd[:, None, :] + m[:, None, :]
        recon = recon * sd + m

        eps = 1e-12
        p_close = nxt[:, :, 3].clamp_min(eps)
        p_high = nxt[:, :, 1].clamp_min(eps)
        p_low = nxt[:, :, 2].clamp_min(eps)
        ref = recon[:, 3].clamp_min(eps)[:, None]
        obs = torch.from_numpy(x_win[:, -1, 3].astype(np.float32)).clamp_min(eps)[:, None]
        return {
            "r": torch.log(p_close / ref).numpy(),               # (B, S)
            "r_raw": torch.log(p_close / obs).numpy(),           # (B, S)
            "logrange": torch.log(p_high / p_low).abs().numpy(),  # (B, S)
            "entropy": ent.numpy(),                              # (B,)
            "recon_close": recon[:, 3].numpy(),
        }

    @torch.no_grad()
    def logits(self, x_win: np.ndarray, stamp_win: np.ndarray) -> np.ndarray:
        """The next-token logits alone - deterministic, and what `check_causality` compares."""
        mean = x_win.mean(axis=1, keepdims=True)
        std = x_win.std(axis=1, keepdims=True)
        xn = np.clip((x_win - mean) / (std + 1e-5), -CLIP, CLIP).astype(np.float32)
        s1, s2 = self.tok.encode(torch.from_numpy(xn), half=True)
        out, _ = self.model.decode_s1(s1, s2, torch.from_numpy(stamp_win.astype(np.float32)))
        return out[:, -1, :].numpy()

    def readout(self, x: np.ndarray, stamp: np.ndarray, ends: np.ndarray,
                *, batch: int = 32, report=None, stats_fn=None) -> dict[str, np.ndarray]:
        """`step` over many rows, in batches. Returns per-row summaries.

        `stats_fn(ends) -> (mean, std)` overrides the causal per-window
        normalisation. It exists for `kronosleak` alone: the default is the only
        setting any score on `research/foundation.md` is reported under.
        """
        keys = ("mean_r", "mean_absr", "sd_r", "p_up", "mean_raw", "mean_logrange", "entropy")
        out = {k: np.empty(len(ends)) for k in keys}
        for i in range(0, len(ends), batch):
            sl = slice(i, min(i + batch, len(ends)))
            xw, sw = windows(x, stamp, ends[sl], self.ctx)
            got = self.step(xw, sw, None if stats_fn is None else stats_fn(ends[sl]))
            r = got["r"]
            out["mean_r"][sl] = r.mean(axis=1)
            out["mean_absr"][sl] = np.abs(r).mean(axis=1)
            out["sd_r"][sl] = r.std(axis=1)
            out["p_up"][sl] = (r > 0).mean(axis=1)
            out["mean_raw"][sl] = got["r_raw"].mean(axis=1)
            out["mean_logrange"][sl] = got["logrange"].mean(axis=1)
            out["entropy"][sl] = got["entropy"]
            if report is not None:
                report(min(i + batch, len(ends)), len(ends))
        return out


# --------------------------------------------------------------------------
# The checks that run before any score
# --------------------------------------------------------------------------


@torch.no_grad()
def verify(model, tokenizer, *, ctx: int = 64, batch: int = 3, samples: int = 5,
           seed: int = 3) -> dict:
    """Prove the cached path is upstream, not an approximation of it.

    Three comparisons, each against the upstream call it replaces:

    * the cached decoder step against `tokenizer.decode` on the full sequence;
    * `_cond_s2` against `Kronos.decode_s2` at one candidate, where the two are
      required to agree exactly rather than approximately;
    * the whole readout against `KronosPredictor.predict` at `pred_len=1`, which
      is the published entry point, on the same window and the same seed.

    The third is the one that matters: it is the difference between "my
    re-implementation is self-consistent" and "my re-implementation is the model
    the authors published".
    """
    torch.manual_seed(seed)
    x = torch.randn(batch, ctx, 6)
    stamp = torch.zeros(batch, ctx, 5)

    s1, s2 = tokenizer.encode(x, half=True)
    full = tokenizer.decode([s1, s2], half=True)

    bits = tokenizer.indices_to_bits([s1[:, :-1], s2[:, :-1]], half=True)
    z = tokenizer.post_quant_embed(bits)
    cache = []
    for layer in tokenizer.decoder:
        z, k, v = _block_context(layer, z)
        cache.append((k, v))
    ctx_recon = tokenizer.head(z)
    zc = tokenizer.post_quant_embed(
        tokenizer.indices_to_bits([s1[:, -1:], s2[:, -1:]], half=True))
    for layer, (k, v) in zip(tokenizer.decoder, cache, strict=True):
        zc = _block_step(layer, zc, k, v, pos=ctx - 1)
    step_recon = tokenizer.head(zc)

    dec_err = float((step_recon[:, 0] - full[:, -1]).abs().max())
    ctx_err = float((ctx_recon - full[:, :-1]).abs().max())
    scale = float(full.abs().max())

    _, context = model.decode_s1(s1, s2, stamp)
    cand = s1[:, -1:].clone()
    mine = _cond_s2(model, context, cand)[:, 0, :]
    theirs = model.decode_s2(context, cand)[:, -1, :]
    s2_err = float((mine - theirs).abs().max())

    return {
        "decode_step_max_abs_err": dec_err,
        "decode_context_max_abs_err": ctx_err,
        "signal_scale": scale,
        "cond_s2_max_abs_err": s2_err,
        "clean": bool(dec_err < 2e-3 * max(scale, 1.0)
                      and ctx_err < 2e-3 * max(scale, 1.0)
                      and s2_err < 1e-3),
    }


def check_causality(reader: Reader, bars: dict[str, np.ndarray], *,
                    at: int | None = None, n_rows: int = 24) -> dict:
    """Poke a future bar; assert no earlier row's next-token logits move.

    The same instrument `seqlab.check_causality` points at the feature matrix,
    pointed at the model. The logits are deterministic, so this is an exact
    comparison and not a tolerance on a sampler. A silent look-ahead is the one
    bug that makes every arm succeed, and a foundation model is the easiest place
    on this project to hide one.
    """
    x, stamp = frame(bars)
    n = len(x)
    idx = n - 20 if at is None else at
    ends = np.linspace(reader.ctx - 1, idx - 1, n_rows).astype(int)
    ends = np.unique(ends[ends < idx])

    xw, sw = windows(x, stamp, ends, reader.ctx)
    before = reader.logits(xw, sw)

    poked = x.copy()
    poked[idx, :4] *= 1.05
    poked[idx, 4:] *= 3.0
    xw2, _ = windows(poked, stamp, ends, reader.ctx)
    after = reader.logits(xw2, sw)

    moved = float(np.abs(before - after).max())
    return {"poked_row": int(idx), "rows_checked": int(len(ends)),
            "max_logit_move": moved, "clean": bool(moved == 0.0)}


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------


def gbm_like(bars: dict[str, np.ndarray], sigma: float, interval: str,
             rng: np.random.Generator) -> dict[str, np.ndarray]:
    """`seqlab.gbm_bars` at a known sigma, wearing the real feed's clock.

    The timestamps are copied from the real series deliberately. Kronos has
    learned temporal embeddings, so a simulated series carrying 1970 dates would
    differ from its target in a way that has nothing to do with the process, and
    the control would be measuring the calendar.
    """
    sim = seqlab.gbm_bars(sigma, len(bars["close"]), interval, rng)
    sim["time"] = bars["time"].astype(float).copy()
    return sim


def measured_sigma(bars: dict[str, np.ndarray], interval: str) -> float:
    r = np.diff(np.log(np.maximum(bars["close"], 1e-12)))
    return float(np.std(r) * math.sqrt(seqlab.PER_YEAR[interval]))


def surrogate_bars(bars: dict[str, np.ndarray], rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Phase-randomised returns, empirical candle geometry, order destroyed.

    `seqlab.phase_surrogate` is defined on a series, and Kronos eats bars, so the
    surrogate has to be rebuilt into OHLCV. **The randomisation is applied to the
    close-to-close returns and to nothing else**, which is the point of the
    control: phase randomisation preserves linear autocorrelation exactly and
    makes the series Gaussian-linear, so the return spectrum survives and
    volatility clustering - which lives in the autocorrelation of `|r|`, a
    nonlinear property - does not.

    Randomising the range or the volume series instead would **preserve**
    clustering, since clustering is linear in those, and the control would
    quietly become a copy of the feed. The wicks are therefore rebuilt from
    dimensionless geometry drawn i.i.d. from the real bars: the marginal shape
    distribution survives, its order does not.
    """
    o, h, low, c = (bars[k].astype(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    r = np.diff(np.log(np.maximum(c, 1e-12)))
    rs = seqlab.phase_surrogate(r, rng)
    if len(rs) < n - 1:
        rs = np.concatenate([rs, rng.permutation(r)[: n - 1 - len(rs)]])
    rs = rs[: n - 1]

    cs = np.empty(n)
    cs[0] = c[0]
    cs[1:] = c[0] * np.exp(np.cumsum(rs))

    s = np.abs(r)
    floor = max(np.quantile(s[s > 0], 0.10) if (s > 0).any() else 1e-9, 1e-12)
    scale = np.maximum(s, floor)
    up = np.log(np.maximum(h[1:], 1e-12) / np.maximum(np.maximum(o[1:], c[1:]), 1e-12)) / scale
    dn = np.log(np.maximum(np.minimum(o[1:], c[1:]), 1e-12) / np.maximum(low[1:], 1e-12)) / scale
    gap = np.log(np.maximum(o[1:], 1e-12) / np.maximum(c[:-1], 1e-12)) / scale
    pool = np.column_stack([up, dn, gap])
    pool = pool[np.isfinite(pool).all(axis=1)]
    draw = pool[rng.integers(0, len(pool), n - 1)]

    mag = np.abs(rs)
    os_ = np.empty(n)
    os_[0] = o[0]
    os_[1:] = cs[:-1] * np.exp(draw[:, 2] * mag)
    top = np.maximum(os_, cs)
    bot = np.minimum(os_, cs)
    hs, ls = top.copy(), bot.copy()
    hs[1:] = top[1:] * np.exp(np.abs(draw[:, 0]) * mag)
    ls[1:] = bot[1:] * np.exp(-np.abs(draw[:, 1]) * mag)

    return {
        "time": bars["time"].astype(float).copy(),
        "open": os_, "high": np.maximum(hs, top), "low": np.minimum(ls, bot),
        "close": cs,
        "volume": rng.permutation(bars["volume"].astype(float)),
        "spread": bars["spread"].astype(float).copy(),
    }


# --------------------------------------------------------------------------
# The baselines every other arm uses
# --------------------------------------------------------------------------


def har_fit(x: np.ndarray, names: tuple[str, ...], y: np.ndarray,
            tr: np.ndarray) -> tuple[np.ndarray, float]:
    """Log-HAR on the seqlab triple, fitted on train rows only.

    Regresses `log realised_{t+1}` on a constant and `log rv1, log rv5, log rv22`
    - the same three scales `har.py` uses in production, which is the whole point
    of `seqlab.HAR` being one tuple. The fit is in logs because realised
    volatility is right-skewed and an OLS in levels is dragged by the tail;
    exponentiating a log fit is biased low, so the train-fitted smearing factor
    `mean(exp(residual))` is carried back, which is Duan's estimator and needs no
    distributional assumption.
    """
    cols = [names.index(k) for k in ("rv1", "rv5", "rv22")]
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.log(np.maximum(x[:, cols], 1e-12))
    target = np.log(np.maximum(y, 1e-12))
    a = np.column_stack([np.ones(len(tr)), z[tr]])
    ok = np.isfinite(a).all(axis=1) & np.isfinite(target[tr])
    if ok.sum() < 40:
        return np.array([np.nan] * 4), 1.0
    beta, *_ = np.linalg.lstsq(a[ok], target[tr][ok], rcond=None)
    resid = target[tr][ok] - a[ok] @ beta
    return beta, float(np.mean(np.exp(resid)))


def har_predict(x: np.ndarray, names: tuple[str, ...], te: np.ndarray,
                beta: np.ndarray, smear: float) -> np.ndarray:
    cols = [names.index(k) for k in ("rv1", "rv5", "rv22")]
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.log(np.maximum(x[te][:, cols], 1e-12))
    a = np.column_stack([np.ones(len(te)), z])
    return np.exp(a @ beta) * smear


def boot_auc(score: np.ndarray, label: np.ndarray, *, draws: int = 400,
             seed: int = 5) -> float:
    """Bootstrap standard error of an AUC, so a number carries its own band."""
    rng = np.random.default_rng(seed)
    n = len(score)
    if n < 50:
        return float("nan")
    vals = [seqlab.auc(score[i], label[i])
            for i in (rng.integers(0, n, n) for _ in range(draws))]
    return float(np.nanstd(vals))


def mc_floor(samples: int = 64, n: int = 400_000, seed: int = 0) -> dict:
    """What the sampling budget itself costs in `seqlab.srel`, on the known null.

    The volatility readout is a mean over `samples` draws from the model's
    predictive law, so it carries Monte-Carlo noise that a closed-form baseline
    does not, and "Kronos loses to the unconditional mean by 0.03" would be
    worthless if the sampler alone cost 0.03.

    On a constant-sigma GBM the one-bar target `|log(c_{t+1}/c_t)|` is
    half-normal, so this is exact rather than a bootstrap: score a *perfect*
    constant forecast of a half-normal target, then score the same forecast
    estimated from `samples` draws, and difference them.
    """
    rng = np.random.default_rng(seed)
    t = np.abs(rng.normal(0, 1, n))
    exact = seqlab.srel(np.full(n, t.mean()), t)
    draws = np.abs(rng.normal(0, 1, (n, samples))).mean(axis=1)
    est = draws * t.mean() / draws.mean()
    return {"samples": samples, "n": n,
            "srel_exact": round(exact, 4),
            "srel_monte_carlo": round(seqlab.srel(est, t), 4),
            "penalty": round(seqlab.srel(est, t) - exact, 4),
            "relative_mc_sd": round(float(est.std() / est.mean()), 4)}


def check_surrogate(n: int = 20_000, seed: int = 3) -> dict:
    """Prove the surrogate destroys what it is supposed to destroy, on a process that has it.

    `surrogate_bars` is only a control if volatility clustering does not survive
    it, and the Volatility family has no clustering to check that on - the
    control would look correct on a feed where it did nothing. So it is checked
    against a GARCH(1,1) path built here, where clustering is present by
    construction: the return spectrum must survive to machine precision and the
    autocorrelation of `|r|` must go to zero.
    """
    rng = np.random.default_rng(seed)
    w, a, b = 1e-8, 0.10, 0.88
    h = np.empty(n)
    r = np.empty(n)
    h[0] = w / (1 - a - b)
    for t in range(1, n):
        r[t - 1] = math.sqrt(h[t - 1]) * rng.normal()
        h[t] = w + a * r[t - 1] ** 2 + b * h[t - 1]
    r[-1] = math.sqrt(h[-1]) * rng.normal()
    c = 1000 * np.exp(np.cumsum(r))
    o = np.concatenate(([1000.0], c[:-1]))
    bars = {
        "time": np.arange(n, dtype=float) * 3600.0, "open": o, "close": c,
        "high": np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.3, n)) * np.abs(r)),
        "low": np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.3, n)) * np.abs(r)),
        "volume": rng.poisson(1800, n).astype(float), "spread": np.full(n, 2.0),
    }
    sur = surrogate_bars(bars, np.random.default_rng(seed + 2))

    def acf(x, k):
        x = x - x.mean()
        return float(np.corrcoef(x[:-k], x[k:])[0, 1])

    out = {}
    for tag, bb in (("garch", bars), ("surrogate", sur)):
        rr = np.diff(np.log(bb["close"]))
        out[tag] = {"acf_r_1": round(acf(rr, 1), 4),
                    "acf_absr_1": round(acf(np.abs(rr), 1), 4),
                    "acf_absr_5": round(acf(np.abs(rr), 5), 4),
                    "acf_absr_22": round(acf(np.abs(rr), 22), 4),
                    "sd": float(rr.std()),
                    "kurtosis": round(float(((rr - rr.mean()) ** 4).mean() / rr.var() ** 2), 3)}
    s1 = np.abs(np.fft.rfft(np.diff(np.log(bars["close"]))))
    s2 = np.abs(np.fft.rfft(np.diff(np.log(sur["close"]))))
    out["spectrum_max_rel_err"] = float(np.max(np.abs(s1 - s2) / np.maximum(s1, 1e-12)))
    out["bars_well_formed"] = bool(
        np.all(sur["high"] >= np.maximum(sur["open"], sur["close"]))
        and np.all(sur["low"] <= np.minimum(sur["open"], sur["close"])))
    out["clean"] = bool(out["spectrum_max_rel_err"] < 1e-6
                        and abs(out["surrogate"]["acf_absr_1"]) < 0.05
                        and out["garch"]["acf_absr_1"] > 0.10
                        and out["bars_well_formed"])
    return out
