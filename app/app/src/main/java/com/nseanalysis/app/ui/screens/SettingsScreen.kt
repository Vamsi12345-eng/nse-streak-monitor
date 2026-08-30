package com.nseanalysis.app.ui.screens

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    feedUrl: String,
    onFeedUrlChange: (String) -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    var draft by remember(feedUrl) { mutableStateOf(feedUrl) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        }
    ) { padding ->
        LazyColumn(
            Modifier.padding(padding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text("Scan feed", style = MaterialTheme.typography.titleSmall,
                             fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "The raw URL of scan.json published by your GitHub Actions " +
                                "workflow. The screener thresholds live in that workflow, " +
                                "not here — change them there and the app follows.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(12.dp))
                        OutlinedTextField(
                            value = draft,
                            onValueChange = { draft = it },
                            label = { Text("Feed URL") },
                            singleLine = false,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Spacer(Modifier.height(8.dp))
                        OutlinedButton(
                            onClick = { onFeedUrlChange(draft) },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Save and refresh") }
                    }
                }
            }

            // The single most common reason a background alert never arrives on
            // a Samsung device, so it gets a card rather than a footnote.
            item {
                Card(
                    Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.tertiaryContainer
                    ),
                ) {
                    Column(Modifier.padding(16.dp)) {
                        Text(
                            "Important on Samsung",
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onTertiaryContainer,
                        )
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "One UI puts unused apps to sleep, which silently stops " +
                                "background refresh — you would simply never get an alert, " +
                                "with nothing to indicate why.\n\n" +
                                "Fix it in two places:\n\n" +
                                "1.  Battery → tap below → set this app to Unrestricted.\n\n" +
                                "2.  Settings → Battery → Background usage limits → make " +
                                "sure this app is NOT in \"Sleeping apps\" or \"Deep " +
                                "sleeping apps\".",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onTertiaryContainer,
                        )
                        Spacer(Modifier.height(12.dp))
                        OutlinedButton(
                            onClick = { openBatterySettings(context) },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Open battery settings") }
                        Spacer(Modifier.height(6.dp))
                        OutlinedButton(
                            onClick = { openNotificationSettings(context) },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Open notification settings") }
                    }
                }
            }

            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text("How this app works", style = MaterialTheme.typography.titleSmall,
                             fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "A scheduled job scans the Nifty 500 after each close and " +
                                "publishes the result as a small JSON file. This app reads " +
                                "that file — it does not talk to any broker, hold any " +
                                "credentials, or place any orders.\n\n" +
                                "Attribution is computed, not generated: the sector move " +
                                "comes from the median of that sector's Nifty 500 members, " +
                                "and the filings come straight from the NSE announcements " +
                                "feed. Nothing on the detail screen is written by a language " +
                                "model.\n\n" +
                                "The Claude button hands that evidence to the Claude app for " +
                                "a deeper read, using your own subscription.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            item {
                Card(
                    Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    ),
                ) {
                    Column(Modifier.padding(16.dp)) {
                        Text(
                            "Not investment advice",
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold,
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "This is a research tool. It surfaces evidence and comparisons " +
                                "so you can form your own view. Price data comes from a " +
                                "free public source and can be wrong, delayed, or missing. " +
                                "Verify every filing at nseindia.com before acting on it.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

private fun openBatterySettings(context: Context) {
    // The per-app details screen is the reliable target: the direct
    // "ignore battery optimizations" dialog is unavailable on some OEM builds
    // and Play-restricted anyway.
    val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
        data = Uri.fromParts("package", context.packageName, null)
    }
    runCatching { context.startActivity(intent) }
}

private fun openNotificationSettings(context: Context) {
    val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
    } else {
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
            .setData(Uri.fromParts("package", context.packageName, null))
    }
    runCatching { context.startActivity(intent) }
}
