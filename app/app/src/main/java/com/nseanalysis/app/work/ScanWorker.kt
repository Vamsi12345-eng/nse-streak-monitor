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
import java.util.concurrent.TimeUnit

const val CHANNEL_ID = "streak_alerts"
private const val WORK_NAME = "nse_scan_refresh"

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
         * Schedules the recurring refresh.
         *
         * Six hours rather than something tighter because the underlying data
         * only changes once a day, after the close. Asking more often would
         * burn battery for nothing and give One UI a reason to throttle the
         * app - and Samsung's "deep sleeping apps" list will defer this work
         * indefinitely regardless unless the user exempts the app, which is
         * why Settings surfaces that as a first-class instruction.
         */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<ScanWorker>(6, TimeUnit.HOURS)
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
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
        }
    }
}
