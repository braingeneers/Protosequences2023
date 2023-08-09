# GenericFigure.py
# Generate a figure like Fig 5, but for an arbitrary subset of experiments.
import argparse
import sys
from fnmatch import fnmatch

import joblib
import matplotlib.pyplot as plt
import numpy as np
from tqdm import tqdm

import hmmsupport
from hmmsupport import get_raster, figure, load_metrics, Model


def three_ints(arg: str):
    a, b, c = arg.split(",")
    return [int(x) - 1 for x in [a, b, c]]


parser = argparse.ArgumentParser()
parser.add_argument("source", type=str, help="Experiment group name")
parser.add_argument(
    "experiments", type=str, nargs="?", default="*", help="Glob pattern for experiments"
)
parser.add_argument(
    "base_exp", type=str, nargs="?", default="*", help="Glob for base experiments"
)
parser.add_argument(
    "--states", type=three_ints, default=None, help="3 states to compare"
)
parser.add_argument(
    "--no-show", action="store_true", help="Don't show the figure, just save it"
)
args = parser.parse_args()

source = args.source
experiments = [
    exp for exp in hmmsupport.all_experiments(source) if fnmatch(exp, args.experiments)
]
base_exps = [exp for exp in experiments if fnmatch(exp, args.base_exp)]

if not base_exps:
    print(
        f"Invalid experiment {args.base_exp} doesn't match any of {experiments}",
        file=sys.stderr,
    )
    sys.exit(1)

surr = "real"
hmm_library = "default"
hmmsupport.figdir("paper")

bin_size_ms = 30
n_states = 10, 20
n_stateses = np.arange(n_states[0], n_states[-1] + 1)

print("Loading fitted HMMs and calculating entropy.")
rasters = {}
for exp in tqdm(experiments):
    r = get_raster(source, exp, bin_size_ms, surr)
    r._burst_default_rms = 4

    def process_model(n):
        m = Model(
            source, exp, bin_size_ms, n, surr, library=hmm_library, recompute_ok=False
        )
        if m._hmm is None:
            print(f"No model for {exp} with {n} states!")
        else:
            m.compute_entropy(r)
        return m

    models = joblib.Parallel(n_jobs=4)(
        joblib.delayed(process_model)(n) for n in n_stateses
    )
    rasters[exp] = r, models

for k in experiments:
    r: hmmsupport.Raster = rasters[k][0]
    totalfr = r.rates("kHz").sum()
    nbursts = len(r.find_bursts())
    print(
        f"{k} has {r.N} units firing at {totalfr:0.2f} "
        f"kHz total with {nbursts} bursts"
    )


def good_models(exp):
    return [m for m in rasters[exp][1] if m is not None]


entropies, entropy_means, baselines, baseline_std = {}, {}, {}, {}
for exp in experiments:
    entropies[exp] = np.array([m.mean_entropy for m in good_models(exp)])
    entropy_means[exp] = entropies[exp].mean(axis=0)
    baselines[exp] = np.mean([m.baseline_entropy for m in good_models(exp)])
    baseline_std[exp] = np.std([m.baseline_entropy for m in good_models(exp)])


def load_unit_order(exp):
    """
    Load the unit ordering from TJ's metadata, if possible. Otherwise return
    a valid unit order that does nothing if used. Also return the "inverse
    unit order" such that inverse_unit_order[i] is the index of unit i.
    """
    srm = load_metrics(exp, only_include=["mean_rate_ordering"])
    if srm:
        unit_order = np.int32(srm["mean_rate_ordering"].flatten() - 1)
    else:
        print("⚠ Metrics not found, cannot separate packet/non-packet units.")
        unit_order = np.arange(rasters[exp][0].N)

    inverse_unit_order = np.zeros_like(unit_order)
    inverse_unit_order[unit_order] = np.arange(rasters[exp][0].N)
    return unit_order, inverse_unit_order


def do_the_whole_giant_figure(base_exp=experiments[0], n_states=15):
    r = rasters[base_exp][0]
    model = rasters[base_exp][1][np.where(n_stateses == n_states)[0][0]]
    h = model.states(r)
    burst_margins = lmargin_h, rmargin_h = -10, 20
    peaks = r.find_bursts(margins=burst_margins)
    state_prob = r.observed_state_probs(h, burst_margins=burst_margins)
    state_order = np.argsort(np.argmax(state_prob, axis=1))
    lmargin, rmargin = model.burst_margins
    unit_order, inverse_unit_order = load_unit_order(base_exp)
    states = sorted(args.states or state_prob[state_order, :].max(1).argsort()[-3:])
    with figure(f"{source} {base_exp}", figsize=(8.5, 8.5)) as f:
        # Subfigure A: example burst rasters.
        idces, times_ms = r.idces_times()
        axes = f.subplots(
            1,
            3,
            gridspec_kw=dict(wspace=0.1, top=0.995, bottom=0.82, left=0.07, right=0.94),
        )
        ax2s = [ax.twinx() for ax in axes]
        subpeaks = np.random.choice(peaks, 3)
        for ax, ax2, peak_float in zip(axes, ax2s, subpeaks):
            peak = int(round(peak_float))
            when = slice(peak + lmargin_h, peak + rmargin_h + 1)
            hsub = np.array([np.nonzero(state_order == s)[0][0] for s in h[when]])
            t_sec = (np.ogrid[when] - peak) * bin_size_ms / 1000
            ax.imshow(
                hsub.reshape((1, -1)),
                cmap="gist_rainbow",
                aspect="auto",
                alpha=0.3,
                vmin=0,
                vmax=n_states - 1,
                extent=[t_sec[0], t_sec[-1], 0.5, r.N + 0.5],
            )
            idces, times_ms = r.subtime(
                when.start * bin_size_ms, when.stop * bin_size_ms
            ).idces_times()
            times = (times_ms - (peak_float - when.start) * bin_size_ms) / 1000
            ax.plot(times, inverse_unit_order[idces] + 1, "ko", markersize=0.5)
            ax.set_ylim(0.5, r.N + 0.5)
            ax.set_xticks([0, 0.5])
            ax.set_xlim(t_sec[0], t_sec[-1])
            ax.set_xlabel("Time from Peak (s)")
            ax.set_yticks([])
            peak_ms = peak * bin_size_ms
            t_ms = np.arange(-500, 1000)
            ax2.plot(t_ms / 1e3, r.coarse_rate()[t_ms + peak_ms], "r")
            ax2.set_yticks([] if ax2 is not ax2s[-1] else [0, ax2.get_yticks()[-1]])
        ax2.set_ylabel("Population Rate (kHz)")
        ymax = np.max([ax.get_ylim()[1] for ax in ax2s])
        for ax in ax2s:
            ax.set_ylim(0, ymax)

        # Subfigure B: state examples.
        BCtop, BCbot = 0.73, 0.5
        Bleft, Bwidth = 0.03, 0.6
        (A, RA), (B, RB), (C, RC) = [
            f.subplots(
                1,
                2,
                gridspec_kw=dict(
                    top=BCtop,
                    bottom=BCbot,
                    width_ratios=[3, 1],
                    wspace=0,
                    left=Bleft + Bwidth * l,
                    right=Bleft + Bwidth * r,
                ),
            )
            for l, r in [(0.06, 0.26), (0.4, 0.61), (0.76, 0.96)]
        ]
        deltas = dBA, dCB = [
            f.subplots(
                gridspec_kw=dict(
                    top=BCtop,
                    bottom=BCbot,
                    left=Bleft + Bwidth * l,
                    right=Bleft + Bwidth * r,
                )
            )
            for l, r in [(0.305, 0.365), (0.655, 0.715)]
        ]

        examples = [A, B, C]
        rates = [RA, RB, RC]
        for ax in examples:
            ax.set_xticks([])
            # ax.set_xlabel('Realizations', rotation=35)
        for ax in rates:
            ax.set_xlim([0, 0.5])
            ax.set_xticks([0, 0.5], ["$0$", "$0.5$"])
            ax.set_xlabel("FR (Hz)")
        for ax in deltas:
            ax.set_xticks([-0.3, 0], ["$-0.3$", "$0$"])
            ax.set_xlim([-0.5, 0.2])
            ax.set_xlabel("$\Delta$FR")
        for ax in examples + rates + deltas:
            ax.set_yticks([])
            ax.set_ylim(0.5, r.N + 0.5)
        A.set_ylabel("Neuron Unit ID")
        A.set_yticks([1, r.N])

        for axS, axH, s in zip(examples, rates, states):
            data = r._raster[h == state_order[s], :][:, unit_order]
            data_sub = data[np.random.choice(data.shape[0], 60), :]
            axS.set_title(f"State {s+1}")
            axS.imshow(
                data_sub.T,
                aspect="auto",
                interpolation="none",
                extent=[0, 1, r.N + 0.5, 0.5],
            )

            axH.plot(
                data.mean(0),
                np.arange(r.N) + 1,
                c=plt.get_cmap("gist_rainbow")(s / (n_states - 1)),
                alpha=0.3,
            )

        for ax, s0, s1 in zip(deltas, states[:-1], states[1:]):
            mu0 = r._raster[h == state_order[s0], :].mean(0)
            mu1 = r._raster[h == state_order[s1], :].mean(0)
            delta = mu1 - mu0
            ax.plot(delta[unit_order], np.arange(r.N) + 1, c="C3", alpha=0.3)

        # Subfigure C: state heatmap.
        axes[0].set_ylabel("Neuron Unit ID")
        axes[0].set_yticks([1, r.N])

        ax = f.subplots(gridspec_kw=dict(top=BCtop, bottom=BCbot, left=0.7, right=0.97))
        im = ax.imshow(
            state_prob[state_order, :],
            vmin=0,
            vmax=1,
            extent=[t_sec[0], t_sec[-1], n_states + 0.5, 0.5],
            aspect="auto",
        )
        ax.set_yticks([1, n_states])
        ax.set_xticks(0.3 * np.arange(-1, 3))
        ax.set_xlabel("Time From Burst Peak (s)")
        ax.set_ylabel("Hidden State Number")
        plt.colorbar(
            im, ax=ax, label="Probability of Observing State", aspect=10, ticks=[0, 1]
        )

        # Subfigure D: entropy.
        en, pr = f.subplots(
            2,
            1,
            gridspec_kw=dict(
                hspace=0.1,
                height_ratios=[3, 2],
                top=0.4,
                bottom=0.05,
                left=0.06,
                right=0.4,
            ),
        )

        time_sec = np.arange(lmargin, rmargin + 1) * bin_size_ms / 1000
        for exp in experiments:
            if exp == base_exp:
                continue
            ent = entropies[exp].mean(0)
            en.plot(time_sec, ent, "-", c="C0", alpha=0.5)
        ent = entropies[base_exp].mean(0)
        en.plot(time_sec, ent, "-", c="C3", lw=3)

        r = rasters[exp][0]
        peaks = r.find_bursts(margins=(lmargin, rmargin))
        poprate = r.coarse_rate()
        for peak in peaks:
            peak_ms = int(round(peak * bin_size_ms))
            t_ms = np.arange(lmargin * bin_size_ms, rmargin * bin_size_ms + 1)
            pr.plot(
                t_ms / 1e3,
                poprate[peak_ms + t_ms[0] : peak_ms + t_ms[-1] + 1],
                "C3",
                alpha=0.2,
            )

        top = 4
        en.set_ylim(0, top)
        en.set_yticks([])
        for a in (en, pr):
            a.set_yticks([])
        en.set_xticks([])

        en.set_ylabel("Entropy (bits)")
        en.set_yticks([0, top])
        pr.set_ylabel("Normalized Pop. FR")
        pr.set_xlabel("Time from Burst Peak (s)")
        f.align_ylabels([en, pr])

        if not args.no_show:
            plt.show()


for exp in base_exps:
    do_the_whole_giant_figure(exp)