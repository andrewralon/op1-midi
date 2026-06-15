import SwiftUI

struct PanKnobView: View {
    @Binding var value: Int   // -63..+63, 0 = center
    let onChange: (Int) -> Void

    @GestureState private var drag: CGFloat = 0
    @State private var base: Int = 0

    var body: some View {
        GeometryReader { geo in
            let sz = min(geo.size.width, geo.size.height)
            let cx = sz / 2
            let cy = sz / 2
            let r  = sz / 2 - 1

            let liveVal  = max(-63, min(63, base + Int(-drag / 1.4)))
            let angleDeg = Double(liveVal) / 63.0 * 130.0
            let rad      = (angleDeg - 90) * Double.pi / 180
            let tipX     = cx + CGFloat(cos(rad)) * r * 0.66
            let tipY     = cy + CGFloat(sin(rad)) * r * 0.66

            ZStack {
                Circle()
                    .fill(Color(hex: "#1c1c1e"))

                Circle()
                    .stroke(Color(hex: "#aaaaaa"), lineWidth: 1)

                // L/R limit ticks at ±130° from 12 o'clock
                limitTick(cx: cx, cy: cy, r: r, deg: -90 - 130)
                    .stroke(Color(hex: "#aaaaaa"), lineWidth: 1.5)
                limitTick(cx: cx, cy: cy, r: r, deg: -90 + 130)
                    .stroke(Color(hex: "#aaaaaa"), lineWidth: 1.5)

                // Indicator — green at center (matches desktop), white off-center
                Path { p in
                    p.move(to: CGPoint(x: cx, y: cy))
                    p.addLine(to: CGPoint(x: tipX, y: tipY))
                }
                .stroke(liveVal == 0 ? C.green : C.text,
                        style: StrokeStyle(lineWidth: 2, lineCap: .round))
            }
            .frame(width: sz, height: sz)
            .contentShape(Circle())
            .gesture(
                DragGesture(minimumDistance: 1)
                    .updating($drag) { g, state, _ in state = g.translation.height }
                    .onEnded { g in
                        let delta = Int(-g.translation.height / 1.4)
                        let newVal = max(-63, min(63, base + delta))
                        base = newVal
                        value = newVal
                        onChange(newVal)
                    }
            )
            .onAppear { base = value }
            .onChange(of: value) { _, v in if drag == 0 { base = v } }
        }
        .aspectRatio(1, contentMode: .fit)
    }

    private func limitTick(cx: CGFloat, cy: CGFloat, r: CGFloat, deg: Double) -> Path {
        let rad = deg * Double.pi / 180
        var p = Path()
        p.move(to: CGPoint(x: cx + CGFloat(cos(rad)) * r * 0.96,
                           y: cy + CGFloat(sin(rad)) * r * 0.96))
        p.addLine(to: CGPoint(x: cx + CGFloat(cos(rad)) * r * 0.74,
                              y: cy + CGFloat(sin(rad)) * r * 0.74))
        return p
    }
}
