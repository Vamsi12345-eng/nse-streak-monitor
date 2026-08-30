package com.nseanalysis.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Mirrors the JSON emitted by the Python engine (`engine/run_scan.py`).
 *
 * Every field the engine may omit is nullable with a default, and the parser
 * is configured to ignore unknown keys, so adding a field to the engine never
 * breaks an installed app.
 */
@Serializable
data class ScanResult(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("generated_at") val generatedAt: String = "",
    val session: String = "",
    val config: ScanConfig = ScanConfig(),
    val market: MarketSummary = MarketSummary(),
    val sectors: List<SectorSummary> = emptyList(),
    val hits: List<Hit> = emptyList(),
    val stats: Stats = Stats(),
    @SerialName("new_alerts") val newAlerts: List<String> = emptyList(),
)

@Serializable
data class ScanConfig(
    @SerialName("daily_gain_pct") val dailyGainPct: Double = 3.0,
    @SerialName("streak_days") val streakDays: Int = 3,
    @SerialName("min_median_turnover_cr") val minTurnoverCr: Double = 5.0,
)

@Serializable
data class MarketSummary(
    @SerialName("median_day_pct") val medianDayPct: Double = 0.0,
    @SerialName("median_streak_pct") val medianStreakPct: Double = 0.0,
    @SerialName("breadth_pct") val breadthPct: Double = 0.0,
    val names: Int = 0,
)

@Serializable
data class SectorSummary(
    val industry: String = "",
    @SerialName("median_day_pct") val medianDayPct: Double = 0.0,
    @SerialName("median_streak_pct") val medianStreakPct: Double = 0.0,
    @SerialName("breadth_pct") val breadthPct: Double = 0.0,
    val members: Int = 0,
    val reliable: Boolean = true,
)

@Serializable
data class Stats(
    val universe: Int = 0,
    @SerialName("with_prices") val withPrices: Int = 0,
    val hits: Int = 0,
    val enriched: Int = 0,
)

@Serializable
data class Hit(
    val symbol: String = "",
    val name: String = "",
    val industry: String = "",
    val isin: String = "",
    @SerialName("last_close") val lastClose: Double = 0.0,
    @SerialName("cumulative_pct") val cumulativePct: Double = 0.0,
    @SerialName("start_date") val startDate: String = "",
    @SerialName("end_date") val endDate: String = "",
    @SerialName("is_current") val isCurrent: Boolean = true,
    @SerialName("median_turnover_cr") val medianTurnoverCr: Double = 0.0,
    @SerialName("volume_ratio") val volumeRatio: Double? = null,
    @SerialName("pct_from_52w_high") val pctFrom52wHigh: Double? = null,
    val returns: Returns = Returns(),
    val days: List<StreakDay> = emptyList(),
    val attribution: Attribution? = null,
    val fundamentals: Fundamentals? = null,
    val benchmark: Benchmark? = null,
    val scorecard: Scorecard? = null,
    @SerialName("research_prompt") val researchPrompt: String = "",
) {
    /** Stable identity for a streak: it changes when the streak extends. */
    val alertKey: String get() = "$symbol@$endDate"
}

@Serializable
data class Returns(
    val m1: Double? = null,
    val m3: Double? = null,
    val y1: Double? = null,
)

@Serializable
data class StreakDay(
    val date: String = "",
    val close: Double = 0.0,
    @SerialName("gain_pct") val gainPct: Double = 0.0,
    val volume: Long = 0,
)

@Serializable
data class Attribution(
    val verdict: String = "",
    val headline: String = "",
    val explanation: List<String> = emptyList(),
    @SerialName("stock_streak_pct") val stockStreakPct: Double = 0.0,
    @SerialName("sector_streak_pct") val sectorStreakPct: Double? = null,
    @SerialName("market_streak_pct") val marketStreakPct: Double = 0.0,
    @SerialName("excess_vs_sector_pct") val excessVsSectorPct: Double? = null,
    @SerialName("sector_breadth_pct") val sectorBreadthPct: Double? = null,
    @SerialName("volume_ratio") val volumeRatio: Double? = null,
    val cautions: List<String> = emptyList(),
    val filings: List<Filing> = emptyList(),
    val headlines: List<Headline> = emptyList(),
)

@Serializable
data class Filing(
    val date: String = "",
    val time: String = "",
    val category: String = "",
    val summary: String = "",
    @SerialName("pdf_url") val pdfUrl: String = "",
    val bucket: String = "neutral",
    val label: String = "",
)

@Serializable
data class Headline(
    val title: String = "",
    val source: String = "",
    val published: String = "",
    val url: String = "",
)

@Serializable
data class Fundamentals(
    val symbol: String = "",
    @SerialName("market_cap_cr") val marketCapCr: Double? = null,
    @SerialName("trailing_pe") val trailingPe: Double? = null,
    @SerialName("forward_pe") val forwardPe: Double? = null,
    @SerialName("price_to_book") val priceToBook: Double? = null,
    @SerialName("roe_pct") val roePct: Double? = null,
    @SerialName("debt_to_equity") val debtToEquity: Double? = null,
    @SerialName("revenue_growth_pct") val revenueGrowthPct: Double? = null,
    @SerialName("earnings_growth_pct") val earningsGrowthPct: Double? = null,
    @SerialName("operating_margin_pct") val operatingMarginPct: Double? = null,
    @SerialName("profit_margin_pct") val profitMarginPct: Double? = null,
    @SerialName("promoter_holding_pct") val promoterHoldingPct: Double? = null,
    @SerialName("institutional_holding_pct") val institutionalHoldingPct: Double? = null,
    @SerialName("dividend_yield_pct") val dividendYieldPct: Double? = null,
    @SerialName("current_ratio") val currentRatio: Double? = null,
    val beta: Double? = null,
    @SerialName("target_mean") val targetMean: Double? = null,
    @SerialName("target_low") val targetLow: Double? = null,
    @SerialName("target_high") val targetHigh: Double? = null,
    @SerialName("analyst_count") val analystCount: Int? = null,
    @SerialName("current_price") val currentPrice: Double? = null,
    @SerialName("business_summary") val businessSummary: String = "",
)

@Serializable
data class Benchmark(
    val industry: String = "",
    val peers: Int = 0,
    @SerialName("trailing_pe") val trailingPe: Double? = null,
    @SerialName("price_to_book") val priceToBook: Double? = null,
    @SerialName("roe_pct") val roePct: Double? = null,
    @SerialName("debt_to_equity") val debtToEquity: Double? = null,
    @SerialName("revenue_growth_pct") val revenueGrowthPct: Double? = null,
    @SerialName("profit_margin_pct") val profitMarginPct: Double? = null,
)

@Serializable
data class Scorecard(
    val factors: List<Factor> = emptyList(),
    @SerialName("bull_case") val bullCase: List<String> = emptyList(),
    @SerialName("bear_case") val bearCase: List<String> = emptyList(),
    val invalidators: List<String> = emptyList(),
    @SerialName("data_gaps") val dataGaps: List<String> = emptyList(),
    @SerialName("bull_count") val bullCount: Int = 0,
    @SerialName("bear_count") val bearCount: Int = 0,
)

@Serializable
data class Factor(
    val name: String = "",
    val value: String = "",
    @SerialName("peer_value") val peerValue: String = "",
    val stance: String = "neutral",
    val note: String = "",
)
