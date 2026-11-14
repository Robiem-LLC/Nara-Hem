package com.robiem.narahem.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.unit.dp
import kotlin.math.cos
import kotlin.math.sin

/** Draws a tab icon from the same 24x24 paths as the iOS app's NaraHemNavIcon. */
@Composable
fun NaraHemTabIcon(kind: Int, color: Color) {
    Canvas(Modifier.size(24.dp)) {
        val path = Path()
        when (kind) {
            0 -> { // Folded map
                path.moveTo(2f, 6f)
                path.lineTo(9f, 3f)
                path.lineTo(15f, 6f)
                path.lineTo(22f, 3f)
                path.lineTo(22f, 18f)
                path.lineTo(15f, 21f)
                path.lineTo(9f, 18f)
                path.lineTo(2f, 21f)
                path.close()
                path.moveTo(9f, 3f)
                path.lineTo(9f, 18f)
                path.moveTo(15f, 6f)
                path.lineTo(15f, 21f)
            }

            1 -> { // Car
                path.moveTo(4f, 15f)
                path.lineTo(6f, 9f)
                path.quadraticTo(6.5f, 7f, 8f, 7f)
                path.lineTo(16f, 7f)
                path.quadraticTo(17.5f, 7f, 18f, 9f)
                path.lineTo(20f, 15f)
                path.lineTo(20f, 19f)
                path.lineTo(17f, 19f)
                path.lineTo(17f, 17f)
                path.lineTo(7f, 17f)
                path.lineTo(7f, 19f)
                path.lineTo(4f, 19f)
                path.close()
                path.moveTo(5f, 13f)
                path.lineTo(19f, 13f)
                path.addOval(Rect(6f, 14f, 8f, 16f))
                path.addOval(Rect(16f, 14f, 18f, 16f))
            }

            2 -> { // Location pin
                path.moveTo(12f, 22f)
                path.cubicTo(9f, 18f, 4.5f, 12f, 4.5f, 9f)
                path.cubicTo(4.5f, 5f, 7.5f, 2f, 12f, 2f)
                path.cubicTo(16.5f, 2f, 19.5f, 5f, 19.5f, 9f)
                path.cubicTo(19.5f, 12f, 15f, 18f, 12f, 22f)
                path.close()
                path.addOval(Rect(9f, 6f, 15f, 12f))
            }

            else -> { // Settings gear
                path.addOval(Rect(5f, 5f, 19f, 19f))
                path.addOval(Rect(9f, 9f, 15f, 15f))
                for (i in 0 until 8) {
                    val a = i * Math.PI / 4.0
                    path.moveTo(12f + (cos(a) * 9).toFloat(), 12f + (sin(a) * 9).toFloat())
                    path.lineTo(12f + (cos(a) * 11).toFloat(), 12f + (sin(a) * 11).toFloat())
                }
            }
        }
        withTransform({ scale(size.width / 24f, size.height / 24f, pivot = Offset.Zero) }) {
            drawPath(
                path,
                color,
                style = Stroke(width = 2f, cap = StrokeCap.Round, join = StrokeJoin.Round)
            )
        }
    }
}
