package com.nseanalysis.app.debug

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.nseanalysis.app.work.ScanWorker

/**
 * Debug-only hook for running a scan immediately:
 *
 *     adb shell am broadcast -a com.nseanalysis.app.RUN_SCAN_NOW -p com.nseanalysis.app
 *
 * The shipped worker is *periodic*, and WorkManager deliberately refuses to run
 * periodic work ahead of its interval - forcing the job through `cmd
 * jobscheduler run` just logs "being executed before schedule" and reschedules.
 * That makes the notification path impossible to exercise on demand, so this
 * enqueues an equivalent one-time request instead.
 *
 * Lives in the debug source set, so it is absent from release builds entirely.
 */
class TestTriggerReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        Log.i(TAG, "manual scan trigger received")
        WorkManager.getInstance(context)
            .enqueue(OneTimeWorkRequestBuilder<ScanWorker>().build())
    }

    private companion object {
        const val TAG = "ScanTrigger"
    }
}
