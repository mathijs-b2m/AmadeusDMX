// The show: the stage edge to edge, glass panels floating over it, the director in the inspector.
import AmadeusKit
import SwiftUI

struct ShowView: View {
    @Environment(AppModel.self) private var model
    @ObservedObject var stage: StageController

    var body: some View {
        @Bindable var model = model
        ZStack {
            if model.mode.renders3D {
                StageView(controller: stage)
                    .ignoresSafeArea()
                    .onAppear { stage.input = { [weak model] in (model?.stageInput(), model?.feed.latestFullFrame) } }
            } else {
                PerformBoard()   // no Metal view at all: nothing is drawn 60 times a second
            }

            if model.mode.renders3D, model.stageInput() == nil {
                ContentUnavailableView("No Set", systemImage: "square.stack.3d.up.slash",
                                       description: Text("Create a set to see the rig here."))
            }

            VStack(spacing: 12) {
                HStack(alignment: .top, spacing: 12) {
                    NowPlayingCard()
                    Spacer(minLength: 12)
                    if !model.feed.decks.isEmpty, model.engineRunning || model.showState == .attached {
                        DecksCard()
                    }
                }
                Spacer()
                HStack(alignment: .bottom, spacing: 12) {
                    if let h = model.feed.hello, model.feed.state == .connected {
                        TimelineCard(hello: h)
                    } else {
                        Spacer()
                    }
                    if model.mode.renders3D { StageControls(stage: stage) }
                }
            }
            .padding(16)
        }
        .inspector(isPresented: $model.showInspector) {
            DirectorInspector()
                .inspectorColumnWidth(min: 280, ideal: 320, max: 420)
        }
    }
}
