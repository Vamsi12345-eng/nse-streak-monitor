package com.nseanalysis.app.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.nseanalysis.app.data.Factor
import com.nseanalysis.app.data.Filing
import com.nseanalysis.app.data.Hit
import com.nseanalysis.app.ui.theme.cautionColor
import com.nseanalysis.app.ui.theme.moveColor

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DetailScreen(hit: Hit?, onBack: () -> Unit) {
    val context = LocalContext.current

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(hit?.symbol ?: "Not found") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        }
    ) { padding ->
        if (hit == null) {
            Box(Modifier.padding(padding).fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("That stock is not in the current scan.")
            }
            return@Scaffold
        }

        LazyColumn(
            Modifier.padding(padding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item { HeaderCard(hit) }

            hit.attribution?.let { a ->
                item {
                    Section("Why it moved") {
                        Text(
                            a.headline,
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                            // Explained vs unexplained, not good vs bad - a
                            // disclosed cause for a large fall is still a fall.
                            color = when (a.verdict) {
                                "unexplained" -> cautionColor()
                                "sector_wide" -> MaterialTheme.colorScheme.onSurfaceVariant
                                else -> MaterialTheme.colorScheme.onSurface
                            },
                        )
                        Spacer(Modifier.height(10.dp))
                        a.explanation.forEach { Bullet(it) }
                    }
                }

                if (a.cautions.isNotEmpty()) {
                    item {
                        Card(
                            Modifier.fillMaxWidth(),
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.errorContainer
                            ),
                        ) {
                            Column(Modifier.padding(16.dp)) {
                                Text(
                                    "Caution",
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = FontWeight.Bold,
                                    color = MaterialTheme.colorScheme.onErrorContainer,
                                )
                                Spacer(Modifier.height(8.dp))
                                a.cautions.forEach {
                                    Text(
                                        "•  $it",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onErrorContainer,
                                        modifier = Modifier.padding(vertical = 2.dp),
                                    )
                                }
                            }
                        }
                    }
                }

                if (a.filings.isNotEmpty()) {
                    item {
                        Section("Exchange filings in the window") {
                            a.filings.forEach { FilingRow(it, context) }
                        }
                    }
                }
            }

            hit.scorecard?.let { sc ->
                item {
                    Section("One-year view") {
                        Text(
                            "${sc.bullCount} supporting / ${sc.bearCount} opposing factors, " +
                                "measured against ${hit.benchmark?.peers ?: 0} sector peers.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(12.dp))
                        sc.factors.forEach { FactorRow(it) }

                        if (sc.bullCase.isNotEmpty()) {
                            SubHeading("Bull case")
                            sc.bullCase.forEach { Bullet(it, moveColor(1.0)) }
                        }
                        if (sc.bearCase.isNotEmpty()) {
                            SubHeading("Bear case")
                            sc.bearCase.forEach { Bullet(it, moveColor(-1.0)) }
                        }
                        if (sc.invalidators.isNotEmpty()) {
                            SubHeading("What would break this thesis")
                            sc.invalidators.forEach { Bullet(it, cautionColor()) }
                        }
                        if (sc.dataGaps.isNotEmpty()) {
                            SubHeading("Data the engine could not get")
                            sc.dataGaps.forEach {
                                Bullet(it, MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            }

            item { AskClaudeCard(hit, context) }

            hit.attribution?.headlines?.takeIf { it.isNotEmpty() }?.let { headlines ->
                item {
                    Section("Recent headlines") {
                        Text(
                            "Unverified, from Google News. Treat as leads, not evidence.",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(8.dp))
                        headlines.forEach { h ->
                            TextButton(onClick = { openUrl(context, h.url) }) {
                                Text(h.title, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            }

            item { Disclaimer() }
        }
    }
}

@Composable
private fun HeaderCard(hit: Hit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(hit.name, style = MaterialTheme.typography.titleMedium)
            Text(
                "${hit.industry}  ·  ${hit.startDate} to ${hit.endDate}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))
            Text(
                "%+.1f%%".format(hit.cumulativePct),
                style = MaterialTheme.typography.displaySmall,
                fontWeight = FontWeight.Bold,
                color = moveColor(hit.cumulativePct),
            )
            Spacer(Modifier.height(4.dp))
            Text(
                hit.days.joinToString("   ") { "${it.date.takeLast(5)}  ${"%+.2f%%".format(it.gainPct)}" },
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
            )
            Spacer(Modifier.height(12.dp))
            HorizontalDivider()
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                MiniStat("Close", "₹${"%,.2f".format(hit.lastClose)}")
                MiniStat("1M", hit.returns.m1?.let { "%+.1f%%".format(it) } ?: "—")
                MiniStat("3M", hit.returns.m3?.let { "%+.1f%%".format(it) } ?: "—")
                MiniStat("1Y", hit.returns.y1?.let { "%+.1f%%".format(it) } ?: "—")
            }
            Spacer(Modifier.height(10.dp))
            Text(
                "₹${"%,.0f".format(hit.medianTurnoverCr)} cr median daily turnover" +
                    (hit.volumeRatio?.let { "  ·  ${"%.1f".format(it)}× normal volume" } ?: "") +
                    (hit.pctFrom52wHigh?.let { "  ·  ${"%.0f".format(it)}% from 52w high" } ?: ""),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun MiniStat(label: String, value: String) {
    Column {
        Text(value, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun AskClaudeCard(hit: Hit, context: Context) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        ),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Default.AutoAwesome,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimaryContainer,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    "Deep dive with Claude",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
            }
            Spacer(Modifier.height(8.dp))
            Text(
                "Sends every number on this screen — the streak, the sector comparison, " +
                    "the filings and the fundamentals — to the Claude app as a research " +
                    "prompt. Uses your existing subscription; no API key, no extra cost.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Spacer(Modifier.height(14.dp))
            Button(onClick = { shareToClaude(context, hit) }, modifier = Modifier.fillMaxWidth()) {
                Text("Open in Claude")
            }
            Spacer(Modifier.height(6.dp))
            OutlinedButton(
                onClick = { copyPrompt(context, hit) },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Default.ContentCopy, contentDescription = null,
                     modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text("Copy prompt")
            }
        }
    }
}

@Composable
private fun FilingRow(filing: Filing, context: Context) {
    val accent = when (filing.bucket) {
        "caution" -> cautionColor()
        "catalyst" -> moveColor(1.0)
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Column(Modifier.padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier
                    .clip(RoundedCornerShape(4.dp))
                    .background(accent.copy(alpha = 0.15f))
                    .padding(horizontal = 6.dp, vertical = 2.dp)
            ) {
                Text(
                    filing.bucket.uppercase(),
                    style = MaterialTheme.typography.labelSmall,
                    color = accent,
                )
            }
            Spacer(Modifier.width(8.dp))
            Text(
                "${filing.date} ${filing.time}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(3.dp))
        Text(filing.category, style = MaterialTheme.typography.bodyMedium)
        if (filing.label.isNotBlank()) {
            Text(
                filing.label,
                style = MaterialTheme.typography.bodySmall,
                color = accent,
            )
        }
        if (filing.pdfUrl.isNotBlank()) {
            TextButton(
                onClick = { openUrl(context, filing.pdfUrl) },
                contentPadding = PaddingValues(0.dp),
            ) {
                Text("Open filing PDF", style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

@Composable
private fun FactorRow(factor: Factor) {
    val color = when (factor.stance) {
        "bull" -> moveColor(1.0)
        "bear" -> moveColor(-1.0)
        "unknown" -> MaterialTheme.colorScheme.onSurfaceVariant
        else -> MaterialTheme.colorScheme.onSurface
    }
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(factor.name, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
        Text(
            factor.value,
            style = MaterialTheme.typography.bodySmall,
            fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.SemiBold,
            color = color,
        )
        Text(
            "  vs ${factor.peerValue}",
            style = MaterialTheme.typography.labelSmall,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun Section(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(10.dp))
            content()
        }
    }
}

@Composable
private fun SubHeading(text: String) {
    Spacer(Modifier.height(14.dp))
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.Bold,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.height(6.dp))
}

@Composable
private fun Bullet(text: String, color: androidx.compose.ui.graphics.Color? = null) {
    Row(Modifier.padding(vertical = 3.dp)) {
        Text("•  ", style = MaterialTheme.typography.bodySmall, color = color
            ?: MaterialTheme.colorScheme.onSurface)
        Text(
            text,
            style = MaterialTheme.typography.bodySmall,
            color = color ?: MaterialTheme.colorScheme.onSurface,
        )
    }
}

// --------------------------------------------------------------------------
// Intents
// --------------------------------------------------------------------------

/** Play Store package for the Claude Android app. */
private const val CLAUDE_PACKAGE = "com.anthropic.claude"

/**
 * Hands the research prompt to Claude, opening the app directly.
 *
 * `Intent.createChooser` always shows the share sheet - that is its entire
 * purpose - so targeting Claude means naming its package on the intent and
 * skipping the chooser altogether. On Android 11+ the package must also be
 * declared in `<queries>` in the manifest, or it is invisible to us and this
 * silently falls back even when Claude is installed.
 *
 * The prompt goes on the clipboard first, so nothing is lost if the receiving
 * app mishandles a payload this size.
 */
private fun shareToClaude(context: Context, hit: Hit) {
    copyPrompt(context, hit, toast = false)

    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, hit.researchPrompt)
        putExtra(Intent.EXTRA_SUBJECT, "${hit.symbol} research")
    }

    // Straight into Claude, no chooser.
    val direct = Intent(send).setPackage(CLAUDE_PACKAGE)
    if (direct.resolveActivity(context.packageManager) != null) {
        runCatching { context.startActivity(direct) }.onSuccess { return }
    }

    // Claude is not installed (or cannot accept the share). Offer the web app,
    // which the prompt is already on the clipboard for, rather than dropping
    // the user into a generic share sheet they did not ask for.
    val web = Intent(Intent.ACTION_VIEW, Uri.parse("https://claude.ai/new"))
    runCatching { context.startActivity(web) }
        .onSuccess {
            Toast.makeText(
                context,
                "Claude app not found - opened claude.ai. Prompt is on your clipboard, paste it.",
                Toast.LENGTH_LONG,
            ).show()
        }
        .onFailure {
            Toast.makeText(context, "Prompt copied to clipboard", Toast.LENGTH_SHORT).show()
        }
}

private fun copyPrompt(context: Context, hit: Hit, toast: Boolean = true) {
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
    clipboard?.setPrimaryClip(
        ClipData.newPlainText("${hit.symbol} research prompt", hit.researchPrompt)
    )
    if (toast) Toast.makeText(context, "Research prompt copied", Toast.LENGTH_SHORT).show()
}

private fun openUrl(context: Context, url: String) {
    if (url.isBlank()) return
    runCatching {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    }
}
