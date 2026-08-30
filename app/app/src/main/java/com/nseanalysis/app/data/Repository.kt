package com.nseanalysis.app.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.nseanalysis.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit

private val Context.dataStore by preferencesDataStore(name = "nse_settings")

private val KEY_FEED_URL = stringPreferencesKey("feed_url")
private val KEY_SEEN = stringSetPreferencesKey("seen_alerts")
private val KEY_LAST_REFRESH = stringPreferencesKey("last_refresh")

/** Result of a refresh, distinguishing "nothing new" from "could not reach". */
sealed interface RefreshOutcome {
    data class Success(val result: ScanResult, val newHits: List<Hit>) : RefreshOutcome
    data class Failure(val message: String, val cached: ScanResult?) : RefreshOutcome
}

class ScanRepository(private val context: Context) {

    private val json = Json {
        // Lets the engine add fields without breaking an already-installed app.
        ignoreUnknownKeys = true
        coerceInputValues = true
    }

    private val http = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private val cacheFile: File get() = File(context.filesDir, "scan.json")

    val feedUrl: Flow<String> = context.dataStore.data.map {
        it[KEY_FEED_URL] ?: BuildConfig.DEFAULT_FEED_URL
    }

    val lastRefresh: Flow<String> = context.dataStore.data.map {
        it[KEY_LAST_REFRESH] ?: ""
    }

    suspend fun setFeedUrl(url: String) {
        context.dataStore.edit { it[KEY_FEED_URL] = url.trim() }
    }

    /** Reads the last successfully downloaded scan, if there is one. */
    suspend fun cached(): ScanResult? = withContext(Dispatchers.IO) {
        runCatching {
            if (cacheFile.exists()) json.decodeFromString<ScanResult>(cacheFile.readText())
            else null
        }.getOrNull()
    }

    /**
     * Downloads the latest scan and reports which hits are new to this device.
     *
     * Newness is tracked locally rather than trusting the feed's own
     * `new_alerts`, because two devices reading the same feed should each get
     * notified once, and a reinstall should not replay a month of alerts as if
     * they had just happened.
     */
    suspend fun refresh(): RefreshOutcome = withContext(Dispatchers.IO) {
        val url = feedUrl.first()
        val request = Request.Builder()
            .url(url)
            .header("Cache-Control", "no-cache")
            .build()

        val body = try {
            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    return@withContext RefreshOutcome.Failure(
                        "Feed returned HTTP ${response.code}", cached()
                    )
                }
                response.body?.string()
            }
        } catch (e: Exception) {
            return@withContext RefreshOutcome.Failure(
                e.message ?: "Could not reach the feed", cached()
            )
        } ?: return@withContext RefreshOutcome.Failure("Empty response", cached())

        val parsed = try {
            json.decodeFromString<ScanResult>(body)
        } catch (e: Exception) {
            return@withContext RefreshOutcome.Failure(
                "Feed is not valid scan JSON: ${e.message}", cached()
            )
        }

        runCatching { cacheFile.writeText(body) }

        val seen = context.dataStore.data.first()[KEY_SEEN] ?: emptySet()
        val newHits = parsed.hits.filter { it.alertKey !in seen }
        context.dataStore.edit { prefs ->
            prefs[KEY_SEEN] = (seen + parsed.hits.map { it.alertKey }).takeLast(2000).toSet()
            prefs[KEY_LAST_REFRESH] = System.currentTimeMillis().toString()
        }
        RefreshOutcome.Success(parsed, newHits)
    }

}

private fun <T> Set<T>.takeLast(n: Int): List<T> = toList().let { it.subList(maxOf(0, it.size - n), it.size) }
