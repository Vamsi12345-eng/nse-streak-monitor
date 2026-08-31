package com.nseanalysis.app.work

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.nseanalysis.app.MainActivity
import com.nseanalysis.app.R
import com.nseanalysis.app.data.Hit
import com.nseanalysis.app.data.RefreshOutcome
import com.nseanalysis.app.data.ScanRepository
import java.time.DayOfWeek
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.concurrent.TimeUnit

const val CHANNEL_ID = "streak_alerts"
private const val WORK_NAME = "nse_scan_refresh"
private val IST: ZoneId = ZoneId.of("Asia/Kolkata")

/**
 * Polls the published scan feed and raises a local notification for hits this
 * device has not seen.
 *
 * Polling rather than push, deliberately: the feed is a ~25 KB static file, so
 * a handful of checks a day costs almost nothing, and it keeps the whole app
 * free of Firebase, server keys and an account to sign into.
 */
class ScanWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        // Runs hourly, but the underlying data changes once a day, after the
        // 15:30 IST close. Outside the window in which a new scan can plausibly
        // have been published there is nothing to fetch, so return without
        // touching the network - by far the most expensive part of a check.
        if (!isPublishWindow()) {
            return Result.success()
        }
        val repo = ScanRepository(applicationContext)
        return when (val outcome = repo.refresh()) {
            is RefreshOutcome.Success -> {
                if (outcome.newHits.isNotEmpty()) {
                    notify(outcome.newHits, outcome.result.config.streakDays)
                }
                Result.success()
            }
            // Retry rather than fail: a transient network drop should not skip
            // the day's alert entirely.
            is RefreshOutcome.Failure -> Result.retry()
        }
    }

    private fun notify(hits: List<Hit>, streakDays: Int) {
        val context = applicationContext
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ActivityCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }

        ensureChannel(context)

        val title = if (hits.size == 1) {
            val h = hits.first()
            "${h.symbol} ${"%+.1f".format(h.cumulativePct)}% over $streakDays days"
        } else {
            "${hits.size} stocks on a $streakDays-day streak"
        }

        // The one-line summary carries the verdict, so the notification itself
        // already distinguishes "the sector rallied" from "nobody has
        // explained this" without needing to be opened.
        val body = hits.take(6).joinToString("\n") { h ->
            val verdict = h.attribution?.headline ?: h.industry
            "${h.symbol}  ${"%+.1f".format(h.cumulativePct)}%  -  $verdict"
        }

        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            if (hits.size == 1) putExtra(MainActivity.EXTRA_SYMBOL, hits.first().symbol)
        }
        val pending = PendingIntent.getActivity(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(hits.firstOrNull()?.attribution?.headline ?: "Tap to see why")
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()

        NotificationManagerCompat.from(context).notify(hits.hashCode(), notification)
    }

    companion object {
        fun ensureChannel(context: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Streak alerts",
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description = "Stocks that gained the threshold % on consecutive days"
            }
            context.getSystemService(NotificationManager::class.java)
                ?.createNotificationChannel(channel)
        }

        /**
         * True when a freshly published scan could plausibly be waiting.
         *
         * NSE closes 15:30 IST; Yahoo publishes the daily bars at no fixed time
         * afterwards and the workflow re-scans every 20 minutes until they land.
         * Checking hourly from the close until late evening on weekdays covers
         * that, and skips roughly two thirds of the day's wakeups outright.
         *
         * Deliberately generous at the end: the scan sometimes only completes
         * once Yahoo has backfilled the slower third of the universe.
         */
        internal fun isPublishWindow(now: ZonedDateTime = ZonedDateTime.now(IST)): Boolean {
            val day = now.dayOfWeek
            if (day == DayOfWeek.SATURDAY || day == DayOfWeek.SUNDAY) return false
            val minutes = now.hour * 60 + now.minute
            return minutes in (15 * 60 + 30)..(23 * 60)
        }

        /**
         * Schedules the recurring refresh.
         *
         * Hourly, but [isPublishWindow] makes most of those wakeups a no-op
         * that never opens a socket, so the cost lands close to the old
         * six-hourly schedule while cutting worst-case alert latency from about
         * six hours to about one.
         *
         * Samsung's "deep sleeping apps" list will defer this work indefinitely
         * regardless unless the user exempts the app, which is why Settings
         * surfaces that as a first-class instruction.
         */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<ScanWorker>(1, TimeUnit.HOURS)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .setBackoffCriteria(
                    androidx.work.BackoffPolicy.EXPONENTIAL,
                    30, TimeUnit.MINUTES,
                )
                .build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                // UPDATE, not KEEP: KEEP leaves an already-scheduled worker on its
                // original period, so an app that upgrades would silently stay on
                // the old six-hour schedule forever.
                ExistingPeriodicWorkPolicy.UPDATE,
                request,
            )
        }
    }
}
