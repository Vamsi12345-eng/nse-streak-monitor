package com.nseanalysis.app

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.nseanalysis.app.data.Hit
import com.nseanalysis.app.data.RefreshOutcome
import com.nseanalysis.app.data.ScanRepository
import com.nseanalysis.app.data.ScanResult
import com.nseanalysis.app.ui.screens.DetailScreen
import com.nseanalysis.app.ui.screens.HomeScreen
import com.nseanalysis.app.ui.screens.SettingsScreen
import com.nseanalysis.app.ui.theme.NseAnalysisTheme
import com.nseanalysis.app.work.ScanWorker
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class UiState(
    val loading: Boolean = false,
    val result: ScanResult? = null,
    val error: String? = null,
    val feedUrl: String = "",
)

class ScanViewModel(app: android.app.Application) : AndroidViewModel(app) {
    private val repo = ScanRepository(app)
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            // Show whatever was cached immediately, then go to the network, so
            // opening the app is never a blank screen waiting on a request.
            val cached = repo.cached()
            _state.value = _state.value.copy(result = cached, loading = true)
            repo.feedUrl.collect { url ->
                _state.value = _state.value.copy(feedUrl = url)
            }
        }
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, error = null)
            _state.value = when (val outcome = repo.refresh()) {
                is RefreshOutcome.Success ->
                    _state.value.copy(loading = false, result = outcome.result, error = null)
                is RefreshOutcome.Failure ->
                    _state.value.copy(
                        loading = false,
                        result = outcome.cached ?: _state.value.result,
                        error = outcome.message,
                    )
            }
        }
    }

    fun setFeedUrl(url: String) {
        viewModelScope.launch {
            repo.setFeedUrl(url)
            refresh()
        }
    }

    /**
     * Finds a stock across every section.
     *
     * Streaks are searched first: a name can appear both as a streak and as
     * today's top gainer, and the streak carries the richer multi-session
     * window, so that is the one worth showing.
     */
    fun hit(symbol: String): Hit? {
        val r = _state.value.result ?: return null
        return (r.hits + r.topGainers + r.topLosers).firstOrNull { it.symbol == symbol }
    }
}

class MainActivity : ComponentActivity() {

    private val requestNotifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        ScanWorker.ensureChannel(this)
        ScanWorker.schedule(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        val deepLinkSymbol = intent?.getStringExtra(EXTRA_SYMBOL)

        setContent {
            NseAnalysisTheme {
                val vm: ScanViewModel = androidx.lifecycle.viewmodel.compose.viewModel()
                val state by vm.state.collectAsStateWithLifecycle()
                val nav = rememberNavController()

                NavHost(
                    navController = nav,
                    startDestination = if (deepLinkSymbol != null) "detail/$deepLinkSymbol" else "home",
                ) {
                    composable("home") {
                        HomeScreen(
                            state = state,
                            onRefresh = vm::refresh,
                            onOpen = { nav.navigate("detail/${it.symbol}") },
                            onSettings = { nav.navigate("settings") },
                        )
                    }
                    composable("detail/{symbol}") { entry ->
                        val symbol = entry.arguments?.getString("symbol").orEmpty()
                        DetailScreen(
                            hit = vm.hit(symbol),
                            onBack = {
                                if (!nav.popBackStack()) nav.navigate("home")
                            },
                        )
                    }
                    composable("settings") {
                        SettingsScreen(
                            feedUrl = state.feedUrl,
                            onFeedUrlChange = vm::setFeedUrl,
                            onBack = { nav.popBackStack() },
                        )
                    }
                }
            }
        }
    }

    companion object {
        const val EXTRA_SYMBOL = "extra_symbol"
    }
}
