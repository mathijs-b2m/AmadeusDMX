// Camera presets, flying through the room, the LED wall scene, zones, haze and exposure.
import AmadeusKit
import SwiftUI

struct StageControls: View {
    @ObservedObject var stage: StageController
    @Environment(AppModel.self) private var model
    @State private var showLook = false

    var body: some View {
        GlassEffectContainer(spacing: 8) {
            HStack(spacing: 8) {
                if stage.fly {
                    Text("WASD move · Q/E down/up · drag to look · ⇧ faster · Esc lands")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .glassEffect()
                }
                ForEach(CameraPreset.allCases) { p in
                    Button {
                        stage.preset = p
                    } label: {
                        Image(systemName: p.symbol).frame(width: 18, height: 18)
                    }
                    .buttonStyle(p == stage.preset ? AnyPrimitiveButtonStyle(.glassProminent) : AnyPrimitiveButtonStyle(.glass))
                    .help(p.rawValue)
                }
                Button {
                    stage.fly.toggle()
                } label: {
                    Image(systemName: "figure.walk.motion").frame(width: 18, height: 18)
                }
                .buttonStyle(stage.fly ? AnyPrimitiveButtonStyle(.glassProminent) : AnyPrimitiveButtonStyle(.glass))
                .help("Fly through the room (F): WASD or arrows move, Q/E down/up, drag to look around, scroll or pinch to move, ⇧ faster. Without flying: WASD still walks, +/− zoom.")
                Menu {
                    Picker("LED Wall", selection: $stage.wallScene) {
                        ForEach(WallScene.allCases) { s in Label(s.title, systemImage: s.symbol).tag(s) }
                    }
                    .pickerStyle(.inline)
                } label: {
                    Image(systemName: stage.wallScene == .auto ? "tv" : stage.wallScene.symbol).frame(width: 18, height: 18)
                }
                .menuIndicator(.hidden)
                .buttonStyle(.glass)
                .help("LED wall: the director's choice, or try one scene")
                .disabled(!(model.stageInput()?.screen ?? false))
                Button {
                    model.showZones.toggle()
                } label: {
                    Image(systemName: "square.dashed").frame(width: 18, height: 18)
                }
                .buttonStyle(model.showZones ? AnyPrimitiveButtonStyle(.glassProminent) : AnyPrimitiveButtonStyle(.glass))
                .help("Show the zones: where beams may (not) go")
                Button {
                    showLook.toggle()
                } label: {
                    Image(systemName: "cloud.fog").frame(width: 18, height: 18)
                }
                .buttonStyle(.glass)
                .popover(isPresented: $showLook, arrowEdge: .top) {
                    Form {
                        Slider(value: $stage.haze, in: 0...1.5) { Text("Haze") }
                        Slider(value: $stage.exposure, in: 0.4...2) { Text("Exposure") }
                        Toggle("Slow orbit", isOn: $stage.autoOrbit)
                    }
                    .frame(width: 260)
                    .padding()
                }
                .help("Haze and exposure")
            }
        }
    }
}
