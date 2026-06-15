import CoreBluetooth
import SwiftUI

struct ContentView: View {
    var body: some View {
        VStack(spacing: 0) {
            TracksView()
                .frame(height: 280)

            Rectangle().fill(C.bg3).frame(height: 1)

            TransportBarView()
                .frame(height: 58)

            Rectangle().fill(C.bg3).frame(height: 1)

            LFOPanelView()
                .frame(maxHeight: .infinity)
        }
        .background(C.bg)
        .preferredColorScheme(.dark)
        .ignoresSafeArea(edges: .bottom)
    }
}

// MARK: - Device picker sheet (used by LFOPanelView)

struct DevicePickerView: View {
    @EnvironmentObject var app: AppState
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section("Discovered Devices") {
                    if app.ble.discovered.isEmpty {
                        Label("Scanning for BLE MIDI devices…", systemImage: "wave.3.right")
                            .foregroundColor(C.dim)
                    } else {
                        ForEach(app.ble.discovered, id: \.identifier) { p in
                            Button {
                                app.ble.connect(p)
                                dismiss()
                            } label: {
                                HStack {
                                    Image(systemName: "pianokeys")
                                    Text(p.name ?? p.identifier.uuidString)
                                        .foregroundColor(C.text)
                                    Spacer()
                                    Image(systemName: "chevron.right")
                                        .foregroundColor(C.dim)
                                }
                            }
                        }
                    }
                }
                Section {
                    Button("Disconnect") {
                        app.ble.disconnect()
                        dismiss()
                    }
                    .foregroundColor(C.red)
                }
            }
            .navigationTitle("BLE MIDI Device")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .preferredColorScheme(.dark)
    }
}
