import SwiftUI

// Horizontal transport bar — buttons use maxHeight: .infinity so ContentView controls height
struct TransportBarView: View {
    @EnvironmentObject var app: AppState

    var body: some View {
        HStack(spacing: 0) {

            TransBtn(symbol: "play.fill",  active: app.isPlaying) { app.play() }
            TransBtn(symbol: "stop.fill",  active: false)          { app.stop() }

            Sep()

            TransBtn(symbol: "backward.end.fill", active: false) { app.tapePrev() }
            TransBtn(symbol: "forward.end.fill",  active: false) { app.tapeNext() }

            Sep()

            // Clock master/slave toggle — metronome icon skinnier+taller via scaleEffect
            Button {
                if app.isClockMaster { app.disableClock() } else { app.enableClock() }
            } label: {
                VStack(spacing: 0) {
                    Image(systemName: "metronome")
                        .font(.system(size: 32, weight: .regular))
                        .scaleEffect(x: 0.65, y: 1.22, anchor: .center)
                        .foregroundColor(app.isClockMaster ? C.green : C.dim)
                    Text(app.isClockMaster ? "app" : "op1")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundColor(app.isClockMaster ? C.green : C.track(1))
                }
                .frame(width: 48)
                .frame(maxHeight: .infinity)
                .background(app.isClockMaster ? C.green.opacity(0.18) : Color.clear)
            }
            .buttonStyle(.plain)

            // BPM: − value +
            Button { app.setBpm(app.bpm - 1) } label: {
                Image(systemName: "minus")
                    .font(.system(size: 12))
                    .frame(width: 30)
                    .frame(maxHeight: .infinity)
                    .background(C.bg3)
                    .foregroundColor(C.text)
            }
            .buttonStyle(.plain)

            Text(String(format: "%.1f", app.bpm))
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundColor(C.text)
                .frame(width: 52)
                .frame(maxHeight: .infinity)
                .lineLimit(1)
                .minimumScaleFactor(0.7)

            Button { app.setBpm(app.bpm + 1) } label: {
                Image(systemName: "plus")
                    .font(.system(size: 12))
                    .frame(width: 30)
                    .frame(maxHeight: .infinity)
                    .background(C.bg3)
                    .foregroundColor(C.text)
            }
            .buttonStyle(.plain)

            Spacer()
        }
        .background(C.bg2)
    }
}

private struct TransBtn: View {
    let symbol: String
    let active: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 15))
                .frame(width: 44)
                .frame(maxHeight: .infinity)
                .background(active ? C.green.opacity(0.18) : Color.clear)
                .foregroundColor(active ? C.green : C.text)
        }
        .buttonStyle(.plain)
    }
}

private struct Sep: View {
    var body: some View {
        Rectangle()
            .fill(C.bg3)
            .frame(width: 1, height: 26)
            .padding(.horizontal, 4)
    }
}
