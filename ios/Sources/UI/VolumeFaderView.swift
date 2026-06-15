import SwiftUI

// Fader includes the digit display so digits update live while dragging
// (display is computed from @GestureState drag, so it updates every frame)
struct VolumeFaderView: View {
    @Binding var value: Double  // 0-99
    let onChange: (Double) -> Void

    private let trackW: CGFloat    = 6
    private let thumbSize: CGFloat = 14  // square rotated 45° = perfect ◇

    @GestureState private var drag: CGFloat = 0
    @State private var base: Double = 0

    var body: some View {
        GeometryReader { geo in
            let h       = geo.size.height
            let travel  = max(1, h - thumbSize)
            let display = max(0, min(99, base - Double(drag / travel * 99)))
            let thumbY  = CGFloat(1.0 - display / 99.0) * travel
            let center  = thumbY + thumbSize / 2

            ZStack(alignment: .center) {

                // ── Fader track + thumb (top-anchored positioning) ──────────
                ZStack(alignment: .top) {
                    // Gray track — always exactly full height, never changes
                    Capsule()
                        .fill(Color(hex: "#484848"))
                        .frame(width: trackW, height: h)
                        .frame(maxWidth: .infinity)

                    // Red fill from thumb center down to bottom
                    let fillH = max(0, h - center)
                    if fillH > 0 {
                        Capsule()
                            .fill(C.red)
                            .frame(width: trackW, height: fillH)
                            .offset(y: center)
                            .frame(maxWidth: .infinity)
                    }

                    Rectangle()
                        .fill(Color.gray)
                        .overlay(Rectangle().stroke(Color.black, lineWidth: 1.5))
                        .frame(width: thumbSize, height: thumbSize)
                        .rotationEffect(.degrees(45))
                        .shadow(color: .black.opacity(0.45), radius: 1.5, y: 1)
                        .offset(y: thumbY)
                        .frame(maxWidth: .infinity)
                }
                .frame(width: geo.size.width, height: h)

                // ── Live digits — always 2 digits, update every drag frame ──
                HStack(alignment: .bottom, spacing: 0) {
                    Text(String(Int(display) / 10))
                        .font(.system(size: 38, weight: .bold, design: .monospaced))
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity, alignment: .trailing)
                        .padding(.trailing, 7)
                    Text(String(Int(display) % 10))
                        .font(.system(size: 38, weight: .bold, design: .monospaced))
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.leading, 7)
                }
                .allowsHitTesting(false)
            }
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 1)
                    .updating($drag) { g, state, _ in state = g.translation.height }
                    .onEnded { g in
                        let delta = Double(g.translation.height / travel * 99)
                        let newVal = max(0, min(99, base - delta))
                        base = newVal
                        value = newVal
                        onChange(newVal)
                    }
            )
            .onAppear { base = value }
            .onChange(of: value) { _, newVal in if drag == 0 { base = newVal } }
        }
    }
}
