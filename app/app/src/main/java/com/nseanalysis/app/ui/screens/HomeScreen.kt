package com.nseanalysis.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.nseanalysis.app.R
import com.nseanalysis.app.UiState
import com.nseanalysis.app.data.Hit
import com.nseanalysis.app.data.ScanResult
import com.nseanalysis.app.ui.theme.cautionColor
import com.nseanalysis.app.ui.theme.moveColor

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    state: UiState,
    onRefresh: () -> Unit,
    onOpen: (Hit) -> Unit,
    onSettings: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(stringResource(R.string.app_name), style = MaterialTheme.typography.titleLarge)
                        state.result?.let {
                            Text(
                                "Session ${it.session}  ·  ${it.stats.universe} stocks scanned",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                },
                actions = {
                    IconButton(onClick = onRefresh) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                    IconButton(onClick = onSettings) {
                        Icon(Icons.Default.Settings, contentDescription = "Settings")
                    }
                },
            )
        }
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (state.loading) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
            }
            state.error?.let { ErrorBanner(it, state.result != null) }

            val result = state.result
            when {
                result == null && state.loading ->
                    CenteredMessage("Loading the latest scan…", showSpinner = true)
                // No spinner here: the fetch has finished and failed. Leaving one
                // spinning would imply the app is still trying.
                result == null -> CenteredMessage(
                    "No data yet.\n\nSet your feed URL in Settings, then tap refresh."
                )
                else -> SectionedContent(state, result, onOpen)
            }
        }
    }
}

private enum class Section(val label: String) {
    STREAKS("Streaks"),
    GAINERS("Gainers"),
    LOSERS("Losers"),
}

@Composable
private fun SectionedContent(state: UiState, result: ScanResult, onOpen: (Hit) -> Unit) {
    // Streaks lead deliberately: they are the rare, deliberately-filtered signal
    // this app exists for. Gainers and losers are always populated and would
    // otherwise bury it under noise that is interesting but not actionable.
    var section by rememberSaveable { mutableStateOf(Section.STREAKS) }

    val rows = when (section) {
        Section.STREAKS -> result.hits
        Section.GAINERS -> result.topGainers
        Section.LOSERS -> result.topLosers
    }

    Column {
        TabRow(selectedTabIndex = section.ordinal) {
            Section.entries.forEach { s ->
                val count = when (s) {
                    Section.STREAKS -> result.hits.size
                    Section.GAINERS -> result.topGainers.size
                    Section.LOSERS -> result.topLosers.size
                }
                Tab(
                    selected = section == s,
                    onClick = { section = s },
                    text = {
                        Text(
                            if (count > 0) "${s.label} ($count)" else s.label,
                            style = MaterialTheme.typography.labelLarge,
                        )
                    },
                )
            }
        }

        LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item { MarketCard(state) }
            item { SectionCaption(section, result) }

            if (rows.isEmpty()) {
                item { EmptySection(section, result) }
                if (section == Section.STREAKS) item { SectorList(state) }
            } else {
                items(rows, key = { it.symbol + "@" + it.endDate }) { hit ->
                    HitCard(hit) { onOpen(hit) }
                }
            }
            item { Disclaimer() }
        }
    }
}

/** One line saying exactly what the visible list is, so no tab is ambiguous. */
@Composable
private fun SectionCaption(section: Section, result: ScanResult) {
    val text = when (section) {
        Section.STREAKS ->
            "Gained ${result.config.dailyGainPct.trimZeros()}% or more on each of " +
                "${result.config.streakDays} consecutive sessions."
        Section.GAINERS ->
            "Biggest single-session gains on ${result.session}, from the Nifty 500."
        Section.LOSERS ->
            "Biggest single-session falls on ${result.session}, from the Nifty 500."
    }
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun EmptySection(section: Section, result: ScanResult) {
    val (title, body) = when (section) {
        Section.STREAKS -> "No stock met the streak rule" to
            ("Nothing gained ${result.config.dailyGainPct.trimZeros()}% on each of " +
                "${result.config.streakDays} consecutive sessions. On a quiet market " +
                "that is the normal result, not a failure.")
        Section.GAINERS -> "No gainers recorded" to
            "No Nifty 500 stock closed higher on ${result.session}, or the scan has " +
                "not run for this session yet."
        Section.LOSERS -> "No losers recorded" to
            "No Nifty 500 stock closed lower on ${result.session}, or the scan has " +
                "not run for this session yet."
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(20.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(6.dp))
            Text(
                body,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * 3.0 -> "3", 1.5 -> "1.5".
 *
 * The threshold is a Double because it is configurable in fractions of a
 * percent. Formatting it with "%.0f" rounds 1.5 up to "2", which makes the app
 * state a screening rule it is not actually using.
 */
private fun Double.trimZeros(): String =
    if (this == toLong().toDouble()) toLong().toString() else toString()

@Composable
private fun MarketCard(state: UiState) {
    val result = state.result ?: return
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        ),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text("Market", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                Stat(
                    "Median move",
                    "%+.2f%%".format(result.market.medianDayPct),
                    moveColor(result.market.medianDayPct),
                )
                Stat("Advancing", "%.0f%%".format(result.market.breadthPct))
                Stat("Matches", "${result.hits.size}")
            }
            Spacer(Modifier.height(8.dp))
            Text(
                "Rule: ≥ ${result.config.dailyGainPct.trimZeros()}% on each of " +
                    "${result.config.streakDays} consecutive sessions",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun Stat(label: String, value: String, color: androidx.compose.ui.graphics.Color? = null) {
    Column {
        Text(
            value,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = color ?: MaterialTheme.colorScheme.onSurface,
        )
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun HitCard(hit: Hit, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(16.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        hit.symbol,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        hit.name,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    "%+.1f%%".format(hit.cumulativePct),
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    color = moveColor(hit.cumulativePct),
                )
            }

            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                hit.days.forEach { day ->
                    DayChip("%+.1f%%".format(day.gainPct))
                }
                if (!hit.isCurrent) DayChip("feed lagging", muted = true)
            }

            hit.attribution?.let { a ->
                Spacer(Modifier.height(12.dp))
                VerdictBadge(a.verdict, a.headline)
                if (a.cautions.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            Icons.Default.WarningAmber,
                            contentDescription = null,
                            tint = cautionColor(),
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(Modifier.width(6.dp))
                        Text(
                            "${a.cautions.size} caution flag${if (a.cautions.size > 1) "s" else ""}",
                            style = MaterialTheme.typography.labelMedium,
                            color = cautionColor(),
                        )
                    }
                }
            }

            Spacer(Modifier.height(10.dp))
            Text(
                "${hit.industry}  ·  ₹${"%,.0f".format(hit.medianTurnoverCr)} cr/day" +
                    (hit.volumeRatio?.let { "  ·  ${"%.1f".format(it)}× volume" } ?: ""),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun DayChip(text: String, muted: Boolean = false) {
    Box(
        Modifier
            .clip(RoundedCornerShape(6.dp))
            .background(
                if (muted) MaterialTheme.colorScheme.surfaceVariant
                else MaterialTheme.colorScheme.primaryContainer
            )
            .padding(horizontal = 8.dp, vertical = 4.dp)
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            fontFamily = FontFamily.Monospace,
            color = if (muted) MaterialTheme.colorScheme.onSurfaceVariant
            else MaterialTheme.colorScheme.onPrimaryContainer,
        )
    }
}

@Composable
fun VerdictBadge(verdict: String, headline: String) {
    // The verdict says how well the move is *explained*, not whether it was
    // good news. Colouring "company_catalyst" green made a disclosed reason for
    // a 9.8% fall read as a positive. Explained is plain, sector-wide is muted,
    // and only "nobody has explained this" earns a warning colour.
    val color = when (verdict) {
        "unexplained" -> cautionColor()
        "sector_wide" -> MaterialTheme.colorScheme.onSurfaceVariant
        else -> MaterialTheme.colorScheme.onSurface
    }
    Text(headline, style = MaterialTheme.typography.bodyMedium, color = color)
}

@Composable
private fun SectorList(state: UiState) {
    val sectors = state.result?.sectors?.take(8) ?: return
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text("Sector moves today", style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.height(8.dp))
            sectors.forEach { s ->
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 3.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(s.industry, style = MaterialTheme.typography.bodySmall)
                    Text(
                        "%+.2f%%".format(s.medianDayPct),
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = moveColor(s.medianDayPct),
                    )
                }
            }
        }
    }
}

@Composable
private fun ErrorBanner(message: String, hasCache: Boolean) {
    Box(
        Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.errorContainer)
            .padding(12.dp)
    ) {
        Text(
            if (hasCache) "$message — showing the last saved scan." else message,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onErrorContainer,
        )
    }
}

@Composable
private fun CenteredMessage(text: String, showSpinner: Boolean = false) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            if (showSpinner) {
                CircularProgressIndicator()
                Spacer(Modifier.height(16.dp))
            }
            Text(
                text,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(32.dp),
            )
        }
    }
}

@Composable
fun Disclaimer() {
    Text(
        "Evidence for your own judgement, not investment advice. Verify every filing " +
            "before acting on it.",
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(vertical = 12.dp),
    )
}
