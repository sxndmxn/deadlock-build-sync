from __future__ import annotations

from deadlock_build_sync.offline.config import RunPaths

from .report_helpers import _markdown_table
from .report_types import CoreReportContext, PathReportContext, ReportTables


def render_report_text(
    paths: RunPaths,
    tables: ReportTables,
    core: CoreReportContext,
    path: PathReportContext,
) -> str:
    manifest = tables.manifest
    ability_scaling = tables.ability_scaling
    evaluation = tables.evaluation
    mechanics = tables.mechanics
    sequence_all_first_item = tables.sequence_all_first_item
    sequence_all_transition = tables.sequence_all_transition
    sequence_evaluation = tables.sequence_evaluation
    sequence_non_component_first_item = tables.sequence_non_component_first_item
    sequence_non_component_position = tables.sequence_non_component_position
    sequence_non_component_transition = tables.sequence_non_component_transition
    account_breadth_summary = core.account_breadth_summary
    calibration_adoption_summary = core.calibration_adoption_summary
    calibration_summary = core.calibration_summary
    cohort = core.cohort
    confounding_summary = core.confounding_summary
    core_path_row = core.core_path_row
    core_path_stability_summary = core.core_path_stability_summary
    duration_summary = core.duration_summary
    hero_count = core.hero_count
    match_count = core.match_count
    matchup_same_lane_spearman = core.matchup_same_lane_spearman
    matchup_stability_summary = core.matchup_stability_summary
    matchup_summary = core.matchup_summary
    matchup_whole_team_spearman = core.matchup_whole_team_spearman
    mechanic_channel_summary = core.mechanic_channel_summary
    overall_overlap = core.overall_overlap
    overall_timing_stability = core.overall_timing_stability
    overlap_summary = core.overlap_summary
    player_match_count = core.player_match_count
    purchase_count = core.purchase_count
    rank_adoption_summary = core.rank_adoption_summary
    rank_coverage = core.rank_coverage
    stability_summary = core.stability_summary
    timing_stability_summary = core.timing_stability_summary
    top_adoption_summary = core.top_adoption_summary
    valid_share = core.valid_share
    api_event_row = core.api_event_row
    adoption_inventory_summary = path.adoption_inventory_summary
    adoption_path_actions = path.adoption_path_actions
    adoption_paths = path.adoption_paths
    adoption_stability = path.adoption_stability
    bootstrap_row = path.bootstrap_row
    cases = path.cases
    daily_end = path.daily_end
    daily_start = path.daily_start
    eight_action_coverage_spearman = path.eight_action_coverage_spearman
    event_count_note = path.event_count_note
    item_state_estimator = path.item_state_estimator
    kelvin_note = path.kelvin_note
    median_eight_action_coverage_shift = path.median_eight_action_coverage_shift
    net_worth_summary = path.net_worth_summary
    observed_max_badge = path.observed_max_badge
    observed_min_badge = path.observed_min_badge
    path_coherence_summary = path.path_coherence_summary
    path_lift_summary = path.path_lift_summary
    phase_text = path.phase_text
    ridge_stability = path.ridge_stability
    state_coverage = path.state_coverage
    state_estimator = path.state_estimator

    return rf"""---
title: Deadlock Item-Ranking Evidence Study
cohort: Configured Emissary I–Eternus V; observed Emissary–Phantom
generated: {manifest.get("generated_at")}
---

# Deadlock Item-Ranking Evidence Study

> [!IMPORTANT]
> The evidence is sufficient to select an algorithm family, but not to treat an item/outcome association as causal. The recommended system deliberately keeps popularity, conditional outcome, uncertainty, tactical interpretation, and path legality as separate layers.

## Executive summary

The frozen post-reset cohort contains **{match_count:,} matches**, **{player_match_count:,} hero-player observations**, **{hero_count} heroes**, and **{purchase_count:,} qualifying purchase events**. The analysis covers ranked normal matches from `{cohort.get("since")}` through `{cohort.get("as_of")}`, using numeric badges **71–115**.

That badge range is the configured acceptance window, not the observed rank coverage. The frozen post-reset sample actually spans **{observed_min_badge}–{observed_max_badge}**: Emissary through Phantom. It contains no Ascendant or Eternus average-rank matches yet, so the combined findings must not be presented as Eternus-specific evidence.

The main findings are:

1. **Use true adoption for popularity.** {event_count_note} That does not make “percentage of the most popular item” an adoption rate: the most popular item is not purchased by every hero-player observation.
2. **Game state predicts outcome; item identity did not add validated ranking signal.** The state-only control is the best held-out predictor with Brier **{state_estimator["brier"]:.6f}**. Adding item identity yields **{item_state_estimator["brier"]:.6f}**, while its train/test item-order Spearman is only **{ridge_stability["median_spearman"]:.4f}**. Do not use the ridge item score to select the core.
3. **Adoption is much more temporally stable than outcome ordering.** Its median train/test Spearman correlation is **{adoption_stability["median_spearman"]:.4f}**, with median top-ten Jaccard **{adoption_stability["median_top10_jaccard"]:.4f}**.
4. **Wilson is an uncertainty display, not the build algorithm.** It is conservative but does not pool related cells or correct purchase-state selection.
5. **Adjustment is only as good as its pre-decision state.** Only **{valid_share:.1%}** of first-purchase rows have a temporally valid net-worth snapshot. Missing opening state must remain missing or become its own stratum.
6. **Provisional rank status does not destabilize popularity here.** Calibrated-versus-provisional adoption has median Spearman **{calibration_adoption_summary.row(0, named=True)["median_spearman"]:.4f}** and median top-ten Jaccard **{calibration_adoption_summary.row(0, named=True)["median_top10_jaccard"]:.4f}**. This supports pooling calibration states for popularity while retaining the audit.
7. **Raw support is not comparable-state support.** Among top-ten adopted items, median overlap-weighted effective support is only **{overall_overlap["median_effective_support_share"]:.1%}** of raw observations; its 10th percentile is **{overall_overlap["p10_effective_support_share"]:.1%}**. Outcome contrasts need phase/position-specific candidate slates and explicit no-overlap abstention.
8. **Matchup outcome deltas do not survive main-effect adjustment reliably.** After subtracting each hero-versus-enemy baseline, median chronological Spearman is **{matchup_same_lane_spearman}** for same-lane residuals and **{matchup_whole_team_spearman}** for whole-team residuals. Counter purchases must start from mechanics and use these residuals only as an abstention-gated audit.
9. **A single marginal top-item path can mix persistent build archetypes.** Eight-action co-purchase coverage varies by hero but is itself highly chronological-stable (train/test Spearman **{eight_action_coverage_spearman:.4f}**). Core selection therefore needs an archetype-aware sequence model, not just marginal adoption sorted by time.

{kelvin_note}

![Held-out estimator error](figures/heldout-estimator-error.png)

## Cohort and evidence contract

| Property | Value |
| --- | --- |
| Mode | Ranked / Normal |
| Configured rank range | Emissary I `[71]` – Eternus V `[115]` |
| Observed average-badge range | `{observed_min_badge}`–`{observed_max_badge}` (Emissary–Phantom) |
| Start | July 30, 2026 rank reset |
| Phases | {phase_text} |
| Active heroes | {hero_count} |
| Purchase unit | First purchase per player-match-item for adoption; all events retained for inflation audits |
| Outcome | Final valid win/loss; observational association |
| Buy-state rule | Latest telemetry snapshot at or before purchase; no future/final fallback |

The complete machine-readable identity is in [`manifest.json`](manifest.json). Public account IDs are never persisted.

## Recommended algorithm architecture

The production design should be a constrained, layered recommender:

1. **Eligibility:** require current-patch support, valid item assets, hero availability, rank cohort, and minimum unique player-match support.
2. **Popularity signal:** calculate `adoption = unique hero-player matches buying the item / eligible hero-player matches`. Keep purchase-event count only as an audit field.
3. **Context baseline:** model phase, buy time, rank, prior net worth, team lead, prior spend, and prior purchase count using only information known at the decision. Use this to identify selection bias and compare like-for-like states—not to award points merely because an item is bought by players already ahead.
4. **Partial pooling and confidence:** shrink sparse hero/tier/item or matchup cells with hierarchical beta-binomial empirical Bayes. Publish posterior intervals or Wilson intervals beside estimates; do not sort the core build by Wilson lower bound alone.
5. **Core selection and archetypes:** shortlist stable, well-supported items by adoption percentile within hero/tier, then require match-level co-purchase coherence. Fit a held-out-selected mixture of purchase-sequence models per hero so the default path comes from one common archetype instead of combining marginally popular but mutually substitutable items. Treat empirical-Bayes outcome and state-adjusted outcome as labeled secondary evidence, not core ranking inputs, until an item-effect model beats the state-only ablation and is temporally stable.
6. **Situational selection:** generate branches from shrunk, main-effect-adjusted same-lane and whole-team item residuals only when item mechanics support the counter rationale and the cell has adequate support, effective sample size, interval width, and temporal stability.
7. **Path optimization:** within an eligible archetype, choose at least eight purchase actions, then optimize observed transition support plus timing and valid net-worth windows while enforcing component credit, inventory slots, active-item limits, total budget, and explicit sells/upgrades. Purchase actions and final inventory count are separate concepts.

Do not collapse these layers into an unexplained fixed weighted average yet. The evidence supports a lexicographic policy today: pass legality/support checks, shortlist by stable adoption within tier, select a co-purchase-coherent archetype, use transition and timing evidence to construct the path, and expose outcome estimates with their uncertainty. A future outcome contribution must earn its place through an incremental state-only ablation, temporal rank stability, and prospective build evaluation.

For hero \(h\) and item \(i\), the core prevalence feature is:

\[
A_{{h,i}} = \frac{{\#\text{{ unique eligible hero-player matches buying }}i}}{{\#\text{{ eligible hero-player matches for }}h}}
\]

After an adoption/support shortlist is fixed, order a candidate path \(\pi=(i_1,\ldots,i_K)\) with a smoothed transition-and-timing objective such as:

\[
J(\pi)=\sum_{{k=2}}^K \log \widetilde P(i_k\mid i_{{k-1}},h)
-\lambda\sum_{{k=1}}^K \rho\!\left(t_k-\widetilde t_{{h,i_k}}\right)
\]

Here \(\widetilde P\) backs sparse transition edges off toward hero/position popularity, \(\widetilde t\) is the observed median purchase time, and \(\rho\) is a robust timing-loss function. Tune the smoothing strength and \(\lambda\) on the validation fold using next-action ranking and path-stability metrics. Components, slots, actives, budget, sells, and flex state remain hard constraints, not score penalties. Observed outcome rate does not enter this objective under the current evidence.

## Estimator comparison

{_markdown_table(evaluation, [("model", "Estimator"), ("observations", "Held-out observations"), ("brier", "Brier ↓"), ("log_loss", "Log loss ↓")])}

Interpretation:

- **Raw outcome rate** is readable but overreacts to sparse cells and purchase-state selection.
- **Wilson lower bound** is conservative but systematically combines effect size with support; it is not a shrinkage model or a causal adjustment.
- **Empirical-Bayes mean** learns a beta prior within each hero and tier, then allows high-support items to remain close to their observed rate.
- **State-adjusted EB** post-stratifies purchase choices over shared phase/net-worth/lead cells and reports coverage.
- **Ridge state model** standardizes item coefficients over a common observed-state sample. It is a sensitivity model, not a causal estimate.

The state-only ablation is decisive for current implementation: the item-augmented ridge model does not improve held-out prediction and its item order is unstable. Use the regularized state model as a confounding diagnostic, empirical Bayes for sparse descriptive cells, and adoption for the core ranking. Wilson remains useful as a visible confidence bound. A cross-fitted doubly robust or hierarchical outcome model is worth testing later, but it should not influence builds unless it adds held-out value beyond state and yields stable item contrasts under adequate overlap.

### Luxury-item confounding

Spearman correlation between item-level raw outcome and common selection variables:

{_markdown_table(confounding_summary, [("scope", "Scope"), ("feature", "Feature"), ("cells", "Cells"), ("median_spearman", "Median Spearman"), ("p10_spearman", "P10"), ("p90_spearman", "P90")])}

Across a hero's full catalog, expensive later purchases mechanically select for matches in which the buyer remained able to shop. Tier stratification removes the cost variation and substantially reduces—but does not eliminate—the time/net-worth association. Item tier must therefore be a comparison stratum, not a feature whose coefficient is interpreted as item power.

### State overlap and effective support

![Raw observations versus overlap-weighted effective support](figures/state-effective-support.png)

{_markdown_table(overlap_summary, [("tier", "Tier"), ("cells", "Top-item cells"), ("median_state_coverage", "Median state coverage"), ("median_effective_support", "Median ESS"), ("minimum_effective_support", "Minimum ESS"), ("median_effective_support_share", "Median ESS/raw"), ("p10_effective_support_share", "P10 ESS/raw")])}

Coverage alone looks reassuring, but the weight concentration does not. Some widely purchased opening items occupy such narrow states that standardizing them over the full hero/tier distribution leaves almost no effective comparison sample. Therefore `state_adjusted_eb` and `ridge_adjusted_rate` are sensitivity columns only. A future causal estimator should define the decision at a specific phase/position, estimate treatment propensity within the available candidate slate, use overlap weights or a cross-fitted doubly robust estimator, report effective support and maximum weight, and abstain when overlap fails.

## Temporal stability

![Ranking stability](figures/ranking-stability.png)

{_markdown_table(stability_summary, [("method", "Method"), ("median_spearman", "Median Spearman"), ("median_top10_jaccard", "Median top-10 Jaccard")])}

These metrics use a strict chronological 60%/20%/20% match split. Stability measures reproducibility across time, not strategic correctness.

The empirical-Bayes lower bound is roughly as stable as Wilson—not better—while the posterior mean is substantially less stable than adoption. Empirical Bayes is still preferable when a coherent partially pooled estimate is needed, but this dataset does not support using either lower bound as the primary ordering.

The stability check was also applied to the complete adoption-derived purchase path:

{_markdown_table(core_path_stability_summary, [("heroes", "Heroes"), ("train_legal", "Train paths legal"), ("test_legal", "Test paths legal"), ("median_item_set_jaccard", "Median item-set Jaccard"), ("minimum_item_set_jaccard", "Minimum item-set Jaccard"), ("median_ordered_lcs_share", "Median ordered overlap"), ("median_same_position_share", "Median same-position share")])}

The median path retains **{core_path_row["median_item_set_jaccard"]:.1%}** item-set agreement and **{core_path_row["median_ordered_lcs_share"]:.1%}** ordered overlap across time, and every split-specific path remains legal. The minimum item-set agreement is **{core_path_row["minimum_item_set_jaccard"]:.1%}**, so per-hero refresh/fingerprinting is still necessary even though the population-level method is stable.

## Sequence coherence

Held-out next-purchase imitation across the chronological test set:

{_markdown_table(sequence_evaluation, [("evaluation_subset", "Subset"), ("model", "Model"), ("test_transitions", "Test transitions"), ("target_coverage", "Target coverage"), ("top1_accuracy", "Top-1"), ("top3_accuracy", "Top-3"), ("top5_accuracy", "Top-5"), ("mean_reciprocal_rank", "MRR")])}

The first-order transition model predicts the exact next item at rank one in **{sequence_all_transition["top1_accuracy"]:.1%}** of **{int(sequence_all_transition["test_transitions"]):,}** held-out transitions and places it in the top five **{sequence_all_transition["top5_accuracy"]:.1%}** of the time. Conditioning that transition on the build's first purchase raises top-one accuracy to **{sequence_all_first_item["top1_accuracy"]:.1%}** and top-five to **{sequence_all_first_item["top5_accuracy"]:.1%}**, with **{sequence_all_first_item["context_coverage"]:.1%}** context coverage. After removing direct component-to-upgrade transitions, first-purchase conditioning raises top-one accuracy from **{sequence_non_component_transition["top1_accuracy"]:.1%}** to **{sequence_non_component_first_item["top1_accuracy"]:.1%}** and top-five from **{sequence_non_component_transition["top5_accuracy"]:.1%}** to **{sequence_non_component_first_item["top5_accuracy"]:.1%}**, versus **{sequence_non_component_position["top1_accuracy"]:.1%}** top-one for the hero-and-purchase-position baseline. These transition metrics remain review evidence only; they do not select runtime actions.

### Deterministic route policy

For each supported legal eight-item core, target ordering is a constrained ranking problem. Every observed pair of target purchases contributes a precedence vote when their timestamps differ. A subset dynamic program chooses the mechanics-legal permutation with maximum pairwise agreement among orders whose component-expanded path admits a nondecreasing soul checkpoint through every observed first-ownership IQR. Item IDs break exact score ties. Equal-time purchases remain an unordered choice set and cast no artificial precedence vote; observed outcome rates remain descriptive and never enter ordering.

Each candidate target order is expanded through the current component graph during constrained optimization. Candidate admission proves the expanded path is unique, legal, soul-window feasible, within the median final-net-worth budget, and resolves to the selected final inventory. A near-variant diagnostic records a materially different runner-up when it retains at least 90% of the winning agreement score. The typed `BuildPolicy` graph is the sole runtime authority; observational transition tables cannot override it or supply a popularity fallback.

## Data-quality findings

### Event count versus adoption

![True adoption of each hero's most-purchased item](figures/top-item-adoption.png)

{event_count_note} The missing denominator is still decisive: dividing by the largest item count makes one item read as 100% for every hero even when only a fraction of eligible matches bought it.

{_markdown_table(top_adoption_summary, [("tier", "Tier"), ("heroes", "Heroes"), ("minimum", "Minimum top adoption"), ("median", "Median top adoption"), ("maximum", "Maximum top adoption")])}

### Aggregate API reconciliation

Across **{api_event_row["cells"]:,}** reconciled hero-item cells, raw and aggregate API event counts have Spearman **{api_event_row["spearman"]:.6f}**. The median absolute relative difference is **{api_event_row["median_absolute_relative_difference"]:.2%}**, consistent with closely aligned but not perfectly simultaneous source snapshots. The API's unique-account count is a median **{api_event_row["median_unique_account_share"]:.2%}** of event volume. Unique accounts are useful for player-concentration audits, but they are not unique hero-player-match adopters and cannot be substituted into the adoption formula.

Match adoption and unique-account breadth nevertheless produce nearly identical orderings:

{_markdown_table(account_breadth_summary, [("hero_tier_cells", "Hero/tier cells"), ("median_spearman", "Median Spearman"), ("median_top10_jaccard", "Median top-10 Jaccard"), ("minimum_top10_jaccard", "Minimum top-10 Jaccard")])}

This supports match adoption as the primary estimand in the current cohort while keeping account breadth as a repeat-player robustness audit.

### Net worth at purchase

![Early net-worth audit](figures/early-net-worth-audit.png)

For early purchases, a large share of players have no telemetry snapshot preceding the buy. Substituting final net worth leaks future information and makes wealthy winners appear wealthy at minute zero. The raw reconstruction quarantines those rows.

Purchase-weighted state coverage:

{_markdown_table(state_coverage, [("phase", "Phase"), ("purchases", "Purchases"), ("own_net_worth_share", "Own net-worth share"), ("team_lead_share", "Team-lead share"), ("complete_team_snapshot_share", "Complete-team snapshot share"), ("complete_share_when_lead_present", "Complete when lead present")])}

{_markdown_table(net_worth_summary, [("phase", "Phase"), ("cells", "Reconciled cells"), ("median_valid_state_share", "Median valid-state share"), ("median_api_raw_ratio", "Median API/raw average ratio"), ("spearman", "API/raw Spearman")])}

The aggregate API and raw prior-snapshot reconstruction agree almost exactly after nine minutes. The opening phase is qualitatively different: its negative cross-item correlation and extreme ratios show that API purchase net worth is not a safe opening-buy feature. Opening recommendations should use observed order/time and item cost, explicitly marking net-worth state unavailable where no prior snapshot exists.

For the 1,520 most-adopted hero/tier/item cells, chronological purchase windows are usually reproducible:

{_markdown_table(timing_stability_summary, [("tier", "Tier"), ("cells", "Top-item cells"), ("median_time_shift_s", "Median buy-time shift (s)"), ("median_time_iqr_overlap", "Median time-IQR overlap"), ("median_net_worth_shift", "Median net-worth shift"), ("median_net_worth_iqr_overlap", "Median net-worth-IQR overlap")])}

Overall, the median train/test buy-time shift is **{overall_timing_stability["median_time_shift_s"]:.1f} seconds** with **{overall_timing_stability["median_time_iqr_overlap"]:.3f}** IQR overlap. The median valid net-worth shift is **{overall_timing_stability["median_net_worth_shift"]:.1f} souls** with **{overall_timing_stability["median_net_worth_iqr_overlap"]:.3f}** overlap. Only **{overall_timing_stability["low_time_overlap_share"]:.1%}** of time windows and **{overall_timing_stability["low_net_worth_overlap_share"]:.1%}** of net-worth windows have overlap below 0.5. Use these as ranges with per-item stability gates, never as exact purchase deadlines; opening net-worth windows still abstain when no prior snapshot exists. See [`timing_window_stability.csv`](tables/timing_window_stability.csv).

### Calibration and cohort composition

The frozen cohort spans **{daily_start} through {daily_end}**. Counts by day and broad rank tier are exported so post-reset population drift can be audited rather than silently mixed into item effects.

{_markdown_table(rank_coverage, [("rank_family", "Rank family"), ("badge_range", "Observed badge range"), ("player_matches", "Player matches"), ("sample_share", "Sample share")])}

{_markdown_table(calibration_summary, [("calibration", "Calibration"), ("player_matches", "Player matches"), ("outcome_rate", "Outcome rate")])}

Calibrated-versus-provisional item adoption remains highly consistent across all **{calibration_adoption_summary.row(0, named=True)["hero_tier_cells"]}** hero/tier cells:

{_markdown_table(calibration_adoption_summary, [("hero_tier_cells", "Hero/tier cells"), ("median_spearman", "Median Spearman"), ("median_top10_jaccard", "Median top-10 Jaccard")])}

Observed rank-family comparisons:

{_markdown_table(rank_adoption_summary, [("comparison", "Comparison"), ("hero_tier_cells", "Hero/tier cells"), ("median_shared_items", "Median shared items"), ("median_spearman", "Median Spearman"), ("median_top10_jaccard", "Median top-10 Jaccard")])}

Emissary and Oracle dominate the sample. Phantom comparisons have fewer shared supported items, and Ascendant/Eternus cannot be evaluated from this frozen window.

See [`cohort_daily_rank.csv`](tables/cohort_daily_rank.csv) for daily composition, [`cohort_badge_counts.csv`](tables/cohort_badge_counts.csv) for exact badge coverage, [`calibration_item_stability.csv`](tables/calibration_item_stability.csv) for provisional-rank sensitivity, and [`rank_family_item_stability.csv`](tables/rank_family_item_stability.csv) for rank-family comparisons.

### Ending-time profiles

{_markdown_table(duration_summary, [("duration_bucket", "Game ending duration"), ("matches", "Hero observations"), ("minimum_hero_rate", "Minimum hero rate"), ("median_hero_rate", "Median hero rate"), ("maximum_hero_rate", "Maximum hero rate")])}

These are hero results among games that *ended* in each interval. They are a duration sensitivity table—not a live, minute-by-minute power curve and not proof of a hero power spike.

### Matchup scope and uncertainty

{_markdown_table(matchup_summary, [("scope", "Enemy scope"), ("supported_cells", "Supported hero-item-enemy cells"), ("observations", "Observations"), ("median_abs_delta", "Median |adjusted item residual|")])}

Whole-enemy-team and assigned-same-lane associations are kept separate. Each item/enemy delta is shrunk toward that item's hero-wide outcome and then subtracts the correspondingly shrunk hero-versus-enemy main effect. This difference-in-differences-style residual prevents a hero's ordinary good or bad matchup from being mislabeled as an item counter, but it remains observational rather than causal. The raw item outcome intervals were also resampled over **{int(bootstrap_row["cells"]):,}** supported top-item cells with **{int(bootstrap_row["replicates"])}** replicates; the median 95% interval width is **{bootstrap_row["median_interval_width"]:.4f}**. A matchup recommendation still requires a compatible item mechanic before it can become counter-purchase prose.

Chronological train/test reproducibility of the main-effect-adjusted item residuals:

{_markdown_table(matchup_stability_summary, [("scope", "Enemy scope"), ("heroes", "Heroes"), ("shared_interactions", "Median shared interactions"), ("median_spearman", "Median Spearman"), ("median_sign_agreement", "Median sign agreement"), ("median_absolute_change", "Median absolute delta change")])}

These matchup residuals are suitable only for evidence-gathering behind a mechanics gate. Their chronological reproducibility determines whether a candidate survives at all; an outcome residual alone must never declare a counter item.

### Mechanics coverage

The frozen client assets resolve **{ability_scaling.height}** signature abilities and expose their active scaled properties without assigning a guessed synergy score:

{_markdown_table(mechanic_channel_summary, [("channel", "Source scaling channel"), ("abilities", "Abilities represented"), ("heroes", "Heroes represented")])}

The sole exception to active scaling-property coverage is Vyper's **Slither**, an innate movement modifier whose current asset payload contains no non-sentinel scaled property. The generator must preserve that absence rather than infer a coefficient.

{_markdown_table(mechanics, [("hero_name", "Hero"), ("signature_abilities", "Signature refs"), ("resolved_abilities", "Resolved"), ("abilities_with_scaling", "Scaling represented")])}

[`hero_ability_scaling.csv`](tables/hero_ability_scaling.csv) preserves ability slot, source class/name, scaled property names, scale functions, specific stat types, and Spirit-damage coefficients. Mechanics are used only to validate item identity, components, cost, inventory capacity, active-item limits, ability references, and an explicit item-to-ability rationale. They are not converted into an unvalidated numeric affinity score.

## All-hero ranking and path artifacts

The current adoption baseline produces **{adoption_paths.height}** legal hero paths with **{", ".join(str(value) for value in sorted(adoption_path_actions))} purchase actions each**. Component upgrades consume their prerequisites, so action count and final inventory count intentionally differ:

{_markdown_table(adoption_inventory_summary, [("final_inventory_items", "Final owned items after upgrades"), ("heroes", "Heroes")])}

This is never a four-item recommendation. The top-ten evidence slate, the 8–12-action purchase path, and the final slot-constrained inventory are separate outputs.

Marginal popularity alone is not sufficient evidence that all ten actions belong to one build. The in-sample co-purchase audit shows:

{_markdown_table(path_coherence_summary, [("population", "Population"), ("matches", "Hero-player matches"), ("share_with_six", "Bought ≥6 path actions"), ("share_with_eight", "Bought ≥8 path actions")])}

Across heroes, median observed-versus-independent co-purchase lift is **{path_lift_summary["median_six_item_lift"]:.3f}** for six actions and **{path_lift_summary["median_eight_item_lift"]:.3f}** for eight. The weakest eight-action lift is only **{path_lift_summary["minimum_eight_item_lift"]:.3f}**, showing that some marginal top-item paths combine alternatives. Long matches barely improve eight-action coverage, so duration attrition is not the whole explanation. These patterns persist chronologically: train/test per-hero eight-action coverage has Spearman **{eight_action_coverage_spearman:.3f}** and median absolute shift **{median_eight_action_coverage_shift:.1%}**. The production algorithm should learn latent purchase archetypes (for example, a small held-out-selected mixture of smoothed first-order sequence models) and require held-out co-purchase lift/coverage before emitting a path. [`path_coherence.csv`](tables/path_coherence.csv) exposes the per-hero audit; current paths remain baselines, not finished build recommendations.

- [`top10_rankings.csv`](tables/top10_rankings.csv) contains exactly ten supported items per hero/tier/method when ten exist.
- [`account_breadth_stability.csv`](tables/account_breadth_stability.csv) compares match adoption with unique-player breadth without persisting account identifiers.
- [`experimental_core_paths.csv`](tables/experimental_core_paths.csv) contains method-specific 8–12-purchase paths capped at 30k souls.
- [`core_path_stability.csv`](tables/core_path_stability.csv) compares adoption-derived train/test paths item-for-item and in order.
- [`path_coherence.csv`](tables/path_coherence.csv) compares full-path co-purchase coverage with an independent-adoption baseline per hero.
- [`path_coherence_temporal.csv`](tables/path_coherence_temporal.csv) checks whether per-hero path coverage reproduces across chronological folds.
- [`matchup_interactions.csv`](tables/matchup_interactions.csv) separates enemy-conditioned item associations from both global item outcomes and hero-matchup main effects.
- [`matchup_temporal_stability.csv`](tables/matchup_temporal_stability.csv) measures whether those adjusted item residuals reproduce chronologically.
- [`item_transitions.csv`](tables/item_transitions.csv) records observed next-item sequences without treating them as causal synergy.
- [`sequence_model_evaluation.csv`](tables/sequence_model_evaluation.csv) compares held-out first-order transitions with hero, phase, and purchase-position popularity baselines.
- [`state_overlap_diagnostics.csv`](tables/state_overlap_diagnostics.csv) reports coverage, Kish effective support, and maximum standardization weight for every hero/tier/item cell.
- [`outcome_confounding_correlations.csv`](tables/outcome_confounding_correlations.csv) quantifies the raw outcome relationship with cost, time, net worth, and adoption before and after tier stratification.
- [`hero_duration_profiles.csv`](tables/hero_duration_profiles.csv) records all-hero outcome sensitivity by game-ending interval.
- [`match_bootstrap_intervals.csv`](tables/match_bootstrap_intervals.csv) records reproducible uncertainty intervals for the ten most-adopted items in every hero/tier cell.
- [`hero_ability_scaling.csv`](tables/hero_ability_scaling.csv) records source-backed scaling channels for all 152 signature abilities.

The experimental paths assume nine base slots, no flex slots, at most four active items, component consumption, and explicit low-tier sells when necessary. They are inspectable research outputs—not Steam builds.

## Representative hero case studies

The ridge-adjusted rows and paths below are retained to make the rejected model's failure mode inspectable; they are comparisons, not recommendations. The adoption method is the current core-selection baseline.

{cases}

## Limitations

- Item choice is not randomized. Even state-standardized associations retain unmeasured skill, role, positioning, objective, and composition confounding.
- Match bootstrap intervals account for match sampling but not repeated-player clustering because public account identifiers are deliberately not persisted. Aggregate unique-account counts show that player-level dependence is nontrivial.
- Opening purchases often precede the first net-worth snapshot.
- Match-end win rate by duration describes games ending in that duration bucket; it is not a live hero power curve.
- Matchup cells are shrunk, main-effect-adjusted descriptive residuals—not causal effects. A counter claim still requires a defensible tactical mechanism, support, overlap, and temporal stability.
- The configured ceiling is Eternus V, but this post-reset sample has no observed average badge above 99. Ascendant- and Eternus-specific conclusions require later data.
- Current-rank results should not be combined with pre-reset numeric badges without a separately labeled sensitivity analysis.

## Reproduction

```bash
cd {paths.root}
uv run deadlock-build-sync refresh-evidence --run-id {paths.run.name}
```

Source endpoints and hashes are recorded under [`raw/`](raw/). Producer code identity
is captured before and after the run; Steam data is never accessed or mutated.

[^wilson]: Wilson intervals describe uncertainty around a binomial proportion; they do not correct selection bias.
[^eb]: Empirical Bayes borrows strength across related cells but remains dependent on the chosen pooling group and likelihood.
"""
