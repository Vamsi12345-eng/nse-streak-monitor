package com.nseanalysis.app.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

// Semantic colours for market direction. Deliberately not the raw red/green of
// most trading apps: this app's job is to make you read the evidence, not to
// flash green and trigger a reflex.
val GainGreen = Color(0xFF1B7F4B)
val GainGreenDark = Color(0xFF6FD39B)
val LossRed = Color(0xFFB3261E)
val LossRedDark = Color(0xFFF2B8B5)
val CautionAmber = Color(0xFF8A5A00)
val CautionAmberDark = Color(0xFFFFD08A)

private val LightColors = lightColorScheme(
    primary = Color(0xFF20524A),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFA7F2E0),
    onPrimaryContainer = Color(0xFF00201A),
    secondary = Color(0xFF4A635C),
    surfaceVariant = Color(0xFFDBE5E0),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF8BD5C5),
    onPrimary = Color(0xFF00382F),
    primaryContainer = Color(0xFF005046),
    onPrimaryContainer = Color(0xFFA7F2E0),
    secondary = Color(0xFFB1CCC4),
    surfaceVariant = Color(0xFF3F4945),
)

@Composable
fun NseAnalysisTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    // One UI users expect Material You wallpaper colours; fall back to the
    // hand-picked scheme on anything older than Android 12.
    val colors = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        darkTheme -> DarkColors
        else -> LightColors
    }
    MaterialTheme(colorScheme = colors, content = content)
}

/** Colour for a percentage move, adapted to the current theme. */
@Composable
fun moveColor(value: Double): Color {
    val dark = isSystemInDarkTheme()
    return when {
        value > 0 -> if (dark) GainGreenDark else GainGreen
        value < 0 -> if (dark) LossRedDark else LossRed
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
}

@Composable
fun cautionColor(): Color = if (isSystemInDarkTheme()) CautionAmberDark else CautionAmber
